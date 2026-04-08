"""
Web 工具集

包含 WebFetch 工具，用于获取网页内容并使用 LLM 处理
"""

import os
import asyncio
import hashlib
import time
from typing import Optional, Dict, Any
from urllib.parse import urlparse
from ..core.tool import Tool, ToolInfo, Parameters, Param

from ..agents.mode_manager import AgentModeManager


# ==================== 缓存管理 ====================

class WebFetchCache:
    """WebFetch 缓存管理器

    实现 15 分钟自清理缓存
    """

    def __init__(self, ttl_seconds: int = 900):  # 默认 15 分钟
        self.ttl = ttl_seconds
        self._cache: Dict[str, Dict[str, Any]] = {}

    def _get_key(self, url: str) -> str:
        """生成缓存键"""
        return hashlib.md5(url.encode()).hexdigest()

    def get(self, url: str) -> Optional[str]:
        """获取缓存内容"""
        key = self._get_key(url)
        if key in self._cache:
            entry = self._cache[key]
            if time.time() - entry['timestamp'] < self.ttl:
                return entry['content']
            else:
                # 过期，删除
                del self._cache[key]
        return None

    def set(self, url: str, content: str) -> None:
        """设置缓存"""
        key = self._get_key(url)
        self._cache[key] = {
            'content': content,
            'timestamp': time.time()
        }

    def clear_expired(self) -> int:
        """清理过期缓存，返回清理数量"""
        now = time.time()
        expired_keys = [
            k for k, v in self._cache.items()
            if now - v['timestamp'] >= self.ttl
        ]
        for key in expired_keys:
            del self._cache[key]
        return len(expired_keys)


# 全局缓存实例
_web_fetch_cache = WebFetchCache()


# ==================== HTML 转 Markdown ====================

def html_to_markdown(html: str) -> str:
    """将 HTML 转换为 Markdown

    尝试使用 html2text，如果不可用则使用简单的正则清理
    """
    try:
        import html2text
        h = html2text.HTML2Text()
        h.ignore_links = False
        h.ignore_images = False
        h.ignore_emphasis = False
        h.body_width = 0  # 不换行
        h.unicode_snob = True
        h.skip_internal_links = True
        h.inline_links = True
        return h.handle(html)
    except ImportError:
        # 回退：使用简单的 HTML 清理
        import re

        # 移除 script 和 style 标签
        text = re.sub(r'<script[^>]*>.*?</script>', '', html, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r'<style[^>]*>.*?</style>', '', text, flags=re.DOTALL | re.IGNORECASE)

        # 移除 HTML 注释
        text = re.sub(r'<!--.*?-->', '', text, flags=re.DOTALL)

        # 转换常见标签
        text = re.sub(r'<br\s*/?>', '\n', text, flags=re.IGNORECASE)
        text = re.sub(r'<p[^>]*>', '\n\n', text, flags=re.IGNORECASE)
        text = re.sub(r'</p>', '', text, flags=re.IGNORECASE)
        text = re.sub(r'<h[1-6][^>]*>(.*?)</h[1-6]>', r'\n\n## \1\n\n', text, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r'<li[^>]*>(.*?)</li>', r'- \1\n', text, flags=re.DOTALL | re.IGNORECASE)

        # 移除所有其他标签
        text = re.sub(r'<[^>]+>', '', text)

        # 解码 HTML 实体
        import html as html_module
        text = html_module.unescape(text)

        # 清理多余空白
        text = re.sub(r'\n{3,}', '\n\n', text)
        text = re.sub(r' {2,}', ' ', text)

        return text.strip()


# ==================== WebFetchTool ====================

class WebFetchTool(Tool):
    """网页获取工具

    获取 URL 内容，转换为 Markdown，并使用 LLM 处理

    功能：
    - 获取网页内容
    - HTML 转 Markdown
    - 使用 prompt 处理内容（通过 LLM）
    - 15 分钟缓存
    - 重定向检测
    """

    # 最大内容长度（字符）
    MAX_CONTENT_LENGTH = 100000

    # 请求超时（秒）
    REQUEST_TIMEOUT = 30

    # User-Agent
    USER_AGENT = "Mozilla/5.0 (compatible; LumosBot/1.0; +https://github.com/lumos)"

    def __init__(
        self,
        mode_manager: Optional[AgentModeManager] = None,
        llm_callback: Optional[Any] = None
    ):
        """初始化 WebFetch 工具

        Args:
            mode_manager: 模式管理器
            llm_callback: LLM 回调函数，用于处理内容
                         签名: async def callback(prompt: str, content: str) -> str
        """
        super().__init__()
        self.mode_manager = mode_manager
        self.llm_callback = llm_callback
        self.name = "web_fetch"
        self.description = """获取网页内容并使用 AI 处理。

使用说明:
- 从指定 URL 获取网页内容
- 自动将 HTML 转换为 Markdown
- 使用 prompt 指定要从页面提取的信息
- 包含 15 分钟缓存，重复请求更快
- HTTP URL 会自动升级为 HTTPS
- 检测跨域重定向并提示

参数:
- url: 要获取的网页 URL（必需）
- prompt: 处理内容的提示词，描述要提取的信息（必需）

示例:
- url: "https://example.com/docs", prompt: "提取 API 文档中的所有端点"
- url: "https://news.site.com/article", prompt: "总结这篇文章的主要观点"
"""
        self.params = [
            Param(
                name="url",
                description="要获取的网页 URL",
                param_type="string",
                required=True
            ),
            Param(
                name="prompt",
                description="处理内容的提示词，描述要从页面提取的信息",
                param_type="string",
                required=True
            ),
        ]

    def invoke(self, inputs: dict, **kwargs) -> str:
        """同步调用"""
        return asyncio.run(self.ainvoke(inputs, **kwargs))

    async def ainvoke(self, inputs: dict, **kwargs) -> str:  # noqa: ARG002
        """异步调用"""
        import aiohttp

        url = inputs.get("url", "").strip()
        prompt = inputs.get("prompt", "").strip()

        # 参数验证
        if not url:
            return "错误: 未指定 URL"
        if not prompt:
            return "错误: 未指定 prompt"

        # URL 验证和规范化
        try:
            parsed = urlparse(url)
            if not parsed.scheme:
                url = "https://" + url
                parsed = urlparse(url)
            elif parsed.scheme == "http":
                # 升级到 HTTPS
                url = url.replace("http://", "https://", 1)
                parsed = urlparse(url)

            if parsed.scheme not in ("http", "https"):
                return f"错误: 不支持的 URL 协议 '{parsed.scheme}'，仅支持 http/https"

            if not parsed.netloc:
                return "错误: 无效的 URL"

        except Exception as e:
            return f"错误: URL 解析失败 - {str(e)}"

        original_host = parsed.netloc

        # 检查缓存
        cached_content = _web_fetch_cache.get(url)
        if cached_content:
            # 使用缓存内容
            return await self._process_content(cached_content, prompt, url, from_cache=True)

        # 获取网页内容
        try:
            import aiohttp

            headers = {
                "User-Agent": self.USER_AGENT,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
                "Accept-Encoding": "gzip, deflate",  # 不使用 br (Brotli)，aiohttp 默认不支持
            }

            timeout = aiohttp.ClientTimeout(total=self.REQUEST_TIMEOUT)

            # 获取代理设置（aiohttp 不会自动读取环境变量）
            proxy = os.environ.get("HTTPS_PROXY") or os.environ.get("HTTP_PROXY")

            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(url, headers=headers, allow_redirects=True, proxy=proxy) as response:
                    # 检查重定向
                    final_url = str(response.url)
                    final_parsed = urlparse(final_url)

                    if final_parsed.netloc != original_host:
                        # 跨域重定向
                        return (
                            f"检测到跨域重定向:\n"
                            f"原始 URL: {url}\n"
                            f"重定向到: {final_url}\n\n"
                            f"请使用新 URL 重新调用 web_fetch 工具。"
                        )

                    # 检查状态码
                    if response.status != 200:
                        return f"错误: HTTP {response.status} - {response.reason}"

                    # 检查内容类型
                    content_type = response.headers.get("Content-Type", "")
                    if "text/html" not in content_type and "application/xhtml" not in content_type:
                        # 非 HTML 内容，尝试直接读取
                        if "text/" in content_type or "application/json" in content_type:
                            content = await response.text()
                        else:
                            return f"错误: 不支持的内容类型 '{content_type}'，仅支持 HTML 和文本"
                    else:
                        content = await response.text()

                    # 检查内容长度
                    if len(content) > self.MAX_CONTENT_LENGTH:
                        content = content[:self.MAX_CONTENT_LENGTH]
                        truncated = True
                    else:
                        truncated = False

        except asyncio.TimeoutError:
            return f"错误: 请求超时（{self.REQUEST_TIMEOUT}秒）"
        except aiohttp.ClientError as e:
            return f"错误: 网络请求失败 - {str(e)}"
        except Exception as e:
            return f"错误: 获取网页失败 - {str(e)}"

        # HTML 转 Markdown
        if "text/html" in content_type or "application/xhtml" in content_type:
            markdown_content = html_to_markdown(content)
        else:
            markdown_content = content

        # 缓存内容
        _web_fetch_cache.set(url, markdown_content)

        # 处理内容
        result = await self._process_content(
            markdown_content, prompt, url,
            from_cache=False, truncated=truncated if 'truncated' in dir() else False
        )

        return result

    async def _process_content(
        self,
        content: str,
        prompt: str,
        url: str,
        from_cache: bool = False,
        truncated: bool = False
    ) -> str:
        """使用 LLM 处理内容

        Args:
            content: Markdown 内容
            prompt: 用户提示词
            url: 原始 URL
            from_cache: 是否来自缓存
            truncated: 内容是否被截断
        """
        # 构建处理提示
        system_prompt = f"""你是一个网页内容分析助手。用户提供了一个网页的内容（已转换为 Markdown），请根据用户的要求分析和提取信息。

网页 URL: {url}
{'[内容来自缓存]' if from_cache else ''}
{'[注意: 内容过长已截断]' if truncated else ''}

请直接回答用户的问题，不要重复网页内容。如果无法从内容中找到相关信息，请明确说明。"""

        user_prompt = f"""用户要求: {prompt}

网页内容:
---
{content[:50000]}
---

请根据上述内容回答用户的要求。"""

        # 如果有 LLM 回调，使用它处理
        if self.llm_callback:
            try:
                result = await self.llm_callback(system_prompt, user_prompt)
                return result
            except Exception as e:
                return f"错误: LLM 处理失败 - {str(e)}\n\n原始内容（前 5000 字符）:\n{content[:5000]}"
        else:
            # 没有 LLM 回调，直接返回内容摘要
            summary_lines = [
                f"URL: {url}",
                f"{'[缓存]' if from_cache else '[新获取]'}",
                f"内容长度: {len(content)} 字符",
                "",
                "--- 内容预览 (前 5000 字符) ---",
                content[:5000],
            ]
            if len(content) > 5000:
                summary_lines.append(f"\n... [还有 {len(content) - 5000} 字符]")

            return "\n".join(summary_lines)

    def get_tool_info(self) -> ToolInfo:
        """获取工具信息"""
        return ToolInfo(
            type="function",
            name=self.name,
            description=self.description,
            parameters=Parameters(
                type="object",
                properties={
                    "url": {
                        "type": "string",
                        "description": "要获取的网页 URL",
                        "format": "uri"
                    },
                    "prompt": {
                        "type": "string",
                        "description": "处理内容的提示词，描述要从页面提取的信息"
                    }
                },
                required=["url", "prompt"]
            )
        )


# ==================== 工具工厂 ====================

def create_web_fetch_tool(
    mode_manager: Optional[AgentModeManager] = None,
    llm_callback: Optional[Any] = None
) -> WebFetchTool:
    """创建 WebFetch 工具实例

    Args:
        mode_manager: 模式管理器
        llm_callback: LLM 回调函数

    Returns:
        WebFetchTool 实例
    """
    return WebFetchTool(mode_manager=mode_manager, llm_callback=llm_callback)
