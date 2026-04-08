"""
Web 搜索工具

提供网络搜索能力，支持多种搜索引擎
"""

import os
import asyncio
import json
from typing import Optional, List, Dict, Any
from urllib.parse import quote_plus
from ..core.tool import Tool, ToolInfo, Parameters, Param

from ..agents.mode_manager import AgentModeManager


# ==================== 搜索结果数据结构 ====================

class SearchResult:
    """搜索结果"""

    def __init__(
        self,
        title: str,
        url: str,
        snippet: str,
        source: str = ""
    ):
        self.title = title
        self.url = url
        self.snippet = snippet
        self.source = source

    def to_dict(self) -> Dict[str, str]:
        return {
            "title": self.title,
            "url": self.url,
            "snippet": self.snippet,
            "source": self.source
        }

    def __str__(self) -> str:
        return f"**{self.title}**\n{self.url}\n{self.snippet}"


# ==================== WebSearchTool ====================

class WebSearchTool(Tool):
    """网络搜索工具

    使用搜索引擎搜索信息，返回搜索结果列表。

    支持的搜索引擎:
    - DuckDuckGo (默认，无需 API Key)
    - Google (需要 API Key)
    - Bing (需要 API Key)
    """

    # 默认搜索结果数量
    DEFAULT_NUM_RESULTS = 10

    # 请求超时（秒）
    REQUEST_TIMEOUT = 30

    def __init__(
        self,
        mode_manager: Optional[AgentModeManager] = None,
        search_engine: str = "duckduckgo",
        api_key: Optional[str] = None,
        session_id: Optional[str] = None
    ):
        """初始化 WebSearch 工具

        Args:
            mode_manager: 模式管理器
            search_engine: 搜索引擎 (duckduckgo, google, bing)
            api_key: API 密钥（Google/Bing 需要）
            session_id: 会话 ID（用于浏览器搜索）
        """
        super().__init__()
        self.mode_manager = mode_manager
        self.search_engine = search_engine.lower()
        self.api_key = api_key
        self.session_id = session_id

        self.name = "web_search"
        self.description = """搜索网络获取信息。

使用说明:
- 输入搜索查询，返回相关网页列表
- 每个结果包含标题、URL 和摘要
- 默认返回 10 条结果
- 可指定搜索结果数量

参数:
- query: 搜索查询（必需）
- num_results: 返回结果数量（可选，默认 10）

示例:
- query: "Python asyncio 教程"
- query: "Cursor AI 编程助手 功能介绍", num_results: 5
"""
        self.params = [
            Param(
                name="query",
                description="搜索查询",
                param_type="string",
                required=True
            ),
            Param(
                name="num_results",
                description="返回结果数量（默认 10）",
                param_type="integer",
                required=False
            ),
        ]

    def invoke(self, inputs: dict, **kwargs) -> str:
        """同步调用"""
        return asyncio.run(self.ainvoke(inputs, **kwargs))

    async def ainvoke(self, inputs: dict, **kwargs) -> str:  # noqa: ARG002
        """异步调用"""
        query = inputs.get("query", "").strip()
        num_results = inputs.get("num_results", self.DEFAULT_NUM_RESULTS)

        if not query:
            return """错误: 未指定搜索查询 (query 参数为空)

请使用以下格式调用 web_search:
{
  "query": "搜索关键词",
  "num_results": 5
}"""

        # 限制结果数量
        num_results = min(max(1, num_results), 20)

        # 根据搜索引擎执行搜索
        try:
            # 默认使用 Brave Search（无需 API Key，无验证码）
            results = await self._search_brave(query, num_results)

            if not results:
                return f"未找到与 '{query}' 相关的结果"

            # 格式化输出
            output_lines = [f"## 搜索结果: {query}\n"]
            for i, result in enumerate(results, 1):
                output_lines.append(f"### {i}. {result.title}")
                output_lines.append(f"**URL**: {result.url}")
                output_lines.append(f"{result.snippet}\n")

            return "\n".join(output_lines)

        except Exception as e:
            return f"错误: 搜索失败 - {str(e)}"

    async def _search_brave(self, query: str, num_results: int) -> List[SearchResult]:
        """使用 Brave Search 搜索

        Brave Search 对自动化友好，无需 API Key，无验证码
        """
        import aiohttp

        url = f"https://search.brave.com/search?q={quote_plus(query)}"

        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "Accept-Encoding": "gzip, deflate",
        }

        timeout = aiohttp.ClientTimeout(total=self.REQUEST_TIMEOUT)
        proxy = os.environ.get("HTTPS_PROXY") or os.environ.get("HTTP_PROXY")

        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url, headers=headers, proxy=proxy) as response:
                if response.status != 200:
                    raise Exception(f"HTTP {response.status}")
                html = await response.text()

        return self._parse_brave_html(html, num_results)

    def _parse_brave_html(self, html: str, num_results: int) -> List[SearchResult]:
        """解析 Brave Search HTML 结果"""
        import re

        results = []

        # 匹配 result-wrapper 块中的搜索结果
        # 提取: URL, 标题, 摘要
        result_pattern = r'<div class="result-wrapper[^"]*"[^>]*>.*?<a href="(https?://[^"]+)"[^>]*>.*?<div class="title[^"]*"[^>]*title="([^"]*)"[^>]*>.*?</a>.*?<div class="content[^"]*">.*?<!---->([^<]*)<'

        matches = re.findall(result_pattern, html, re.DOTALL)

        seen_urls = set()
        for url, title, snippet in matches:
            if len(results) >= num_results:
                break
            # 过滤 Brave 自身链接
            if "brave.com" in url or "cdn.search.brave" in url:
                continue
            # 去重
            if url in seen_urls:
                continue
            seen_urls.add(url)

            # 清理标题和摘要
            title = title.strip() or url
            snippet = snippet.strip()

            results.append(SearchResult(
                title=title,
                url=url,
                snippet=snippet,
                source="Brave"
            ))

        # 如果正则没匹配到，回退到简单 URL 提取
        if not results:
            url_pattern = r'<a[^>]*href="(https?://[^"]+)"[^>]*>'
            urls = re.findall(url_pattern, html)
            for u in urls[:num_results]:
                if "brave.com" in u or "cdn.search.brave" in u:
                    continue
                if u in seen_urls:
                    continue
                seen_urls.add(u)
                from urllib.parse import urlparse
                parsed = urlparse(u)
                domain = parsed.netloc.replace("www.", "")
                results.append(SearchResult(
                    title=domain,
                    url=u,
                    snippet="",
                    source="Brave"
                ))
                if len(results) >= num_results:
                    break

        return results

    async def _search_duckduckgo(self, query: str, num_results: int) -> List[SearchResult]:
        """使用 DuckDuckGo 搜索

        使用 DuckDuckGo HTML 搜索页面解析结果
        """
        import aiohttp

        # DuckDuckGo HTML 搜索 URL
        url = f"https://html.duckduckgo.com/html/?q={quote_plus(query)}"

        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "Accept-Encoding": "gzip, deflate",  # 不使用 br (Brotli)，aiohttp 默认不支持
        }

        timeout = aiohttp.ClientTimeout(total=self.REQUEST_TIMEOUT)

        # 获取代理设置
        proxy = os.environ.get("HTTPS_PROXY") or os.environ.get("HTTP_PROXY")

        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url, headers=headers, proxy=proxy) as response:
                # DuckDuckGo 有时返回 202 (Accepted)，也包含有效结果
                if response.status not in (200, 202):
                    raise Exception(f"HTTP {response.status}")

                html = await response.text()

        # 解析 HTML 提取搜索结果
        results = self._parse_duckduckgo_html(html, num_results)
        return results

    def _parse_duckduckgo_html(self, html: str, num_results: int) -> List[SearchResult]:
        """解析 DuckDuckGo HTML 搜索结果"""
        import re

        results = []

        # 查找所有搜索结果块
        # DuckDuckGo HTML 结果格式: <div class="result">...</div>
        result_pattern = r'<div class="result[^"]*"[^>]*>.*?</div>\s*</div>'
        result_blocks = re.findall(result_pattern, html, re.DOTALL)

        for block in result_blocks[:num_results]:
            # 提取标题和 URL
            title_match = re.search(r'<a[^>]*class="result__a"[^>]*href="([^"]*)"[^>]*>([^<]*)</a>', block)
            if not title_match:
                continue

            url = title_match.group(1)
            title = title_match.group(2).strip()

            # 提取摘要
            snippet_match = re.search(r'<a[^>]*class="result__snippet"[^>]*>([^<]*(?:<[^>]*>[^<]*)*)</a>', block)
            snippet = ""
            if snippet_match:
                snippet = re.sub(r'<[^>]+>', '', snippet_match.group(1)).strip()

            if title and url:
                results.append(SearchResult(
                    title=title,
                    url=url,
                    snippet=snippet,
                    source="DuckDuckGo"
                ))

        return results

    async def _search_google(self, query: str, num_results: int) -> List[SearchResult]:
        """使用 Google Custom Search API 搜索

        需要设置 GOOGLE_API_KEY 和 GOOGLE_CSE_ID 环境变量
        """
        import aiohttp

        api_key = self.api_key or os.environ.get("GOOGLE_API_KEY")
        cse_id = os.environ.get("GOOGLE_CSE_ID")

        if not api_key or not cse_id:
            raise Exception("Google 搜索需要设置 GOOGLE_API_KEY 和 GOOGLE_CSE_ID 环境变量")

        url = "https://www.googleapis.com/customsearch/v1"
        params = {
            "key": api_key,
            "cx": cse_id,
            "q": query,
            "num": min(num_results, 10)  # Google API 最多返回 10 条
        }

        timeout = aiohttp.ClientTimeout(total=self.REQUEST_TIMEOUT)

        # 获取代理设置
        proxy = os.environ.get("HTTPS_PROXY") or os.environ.get("HTTP_PROXY")

        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url, params=params, proxy=proxy) as response:
                if response.status != 200:
                    error_text = await response.text()
                    raise Exception(f"HTTP {response.status}: {error_text}")

                data = await response.json()

        results = []
        for item in data.get("items", []):
            results.append(SearchResult(
                title=item.get("title", ""),
                url=item.get("link", ""),
                snippet=item.get("snippet", ""),
                source="Google"
            ))

        return results

    async def _search_bing(self, query: str, num_results: int) -> List[SearchResult]:
        """使用 Bing Search API 搜索

        需要设置 BING_API_KEY 环境变量
        """
        import aiohttp

        api_key = self.api_key or os.environ.get("BING_API_KEY")

        if not api_key:
            raise Exception("Bing 搜索需要设置 BING_API_KEY 环境变量")

        url = "https://api.bing.microsoft.com/v7.0/search"
        headers = {
            "Ocp-Apim-Subscription-Key": api_key
        }
        params = {
            "q": query,
            "count": num_results,
            "mkt": "zh-CN"
        }

        timeout = aiohttp.ClientTimeout(total=self.REQUEST_TIMEOUT)

        # 获取代理设置
        proxy = os.environ.get("HTTPS_PROXY") or os.environ.get("HTTP_PROXY")

        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url, headers=headers, params=params, proxy=proxy) as response:
                if response.status != 200:
                    error_text = await response.text()
                    raise Exception(f"HTTP {response.status}: {error_text}")

                data = await response.json()

        results = []
        for item in data.get("webPages", {}).get("value", []):
            results.append(SearchResult(
                title=item.get("name", ""),
                url=item.get("url", ""),
                snippet=item.get("snippet", ""),
                source="Bing"
            ))

        return results

    async def _search_with_browser(self, query: str, num_results: int) -> List[SearchResult]:
        """使用浏览器搜索 Google（Playwright）

        使用真实浏览器搜索，避免反爬虫拦截
        """
        try:
            from .browser_tools import BrowserOpenTool, BrowserSnapshotTool
            import json

            search_url = f"https://www.bing.com/search?q={quote_plus(query)}"

            # 使用浏览器工具打开搜索页面
            open_tool = BrowserOpenTool(self.mode_manager, self.session_id)
            open_result = await open_tool.ainvoke({"url": search_url})
            if "错误" in open_result:
                return []

            # 等待页面加载
            import asyncio
            await asyncio.sleep(2)

            # 获取页面快照
            snapshot_tool = BrowserSnapshotTool(self.mode_manager, self.session_id)
            snapshot_result = await snapshot_tool.ainvoke({})

            # 解析快照结果
            try:
                snapshot_data = json.loads(snapshot_result)
            except json.JSONDecodeError:
                return []

            if not snapshot_data.get("success"):
                return []

            # 从快照中提取搜索结果
            results = []
            refs = snapshot_data.get("data", {}).get("refs", {})

            for ref_id, ref_data in refs.items():
                if len(results) >= num_results:
                    break
                role = ref_data.get("role", "")
                name = ref_data.get("name", "")
                if role == "link" and name and len(name) > 10:
                    results.append(SearchResult(
                        title=name[:100],
                        url=f"google_ref:{ref_id}",
                        snippet="",
                        source="Google (Browser)"
                    ))

            return results
        except Exception:
            return []

    def get_tool_info(self) -> ToolInfo:
        """获取工具信息"""
        return ToolInfo(
            type="function",
            name=self.name,
            description=self.description,
            parameters=Parameters(
                type="object",
                properties={
                    "query": {
                        "type": "string",
                        "description": "搜索查询"
                    },
                    "num_results": {
                        "type": "integer",
                        "description": "返回结果数量（默认 10）"
                    }
                },
                required=["query"]
            )
        )


# ==================== 工具工厂 ====================

def create_web_search_tool(
    mode_manager: Optional[AgentModeManager] = None,
    search_engine: str = "duckduckgo",
    api_key: Optional[str] = None
) -> WebSearchTool:
    """创建 WebSearch 工具实例

    Args:
        mode_manager: 模式管理器
        search_engine: 搜索引擎 (duckduckgo, google, bing)
        api_key: API 密钥

    Returns:
        WebSearchTool 实例
    """
    return WebSearchTool(
        mode_manager=mode_manager,
        search_engine=search_engine,
        api_key=api_key
    )
