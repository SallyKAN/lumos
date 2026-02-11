"""
浏览器自动化工具

基于 agent-browser 封装的浏览器自动化工具集，为 AI Agent 提供网页交互能力。

依赖要求:
    npm install -g agent-browser
    agent-browser install
"""

import os
import asyncio
import subprocess
from typing import Optional, List, Tuple
from ..core.tool import Tool, ToolInfo, Parameters, Param

from ..agents.mode_manager import AgentModeManager, AgentMode


# ==================== 浏览器工具基类 ====================

class BrowserToolBase(Tool):
    """浏览器工具基类

    提供 agent-browser 依赖检测和命令执行的通用功能。
    """

    _agent_browser_available: Optional[bool] = None
    _install_message = """agent-browser 未安装。请执行以下命令安装：

1. 安装 agent-browser:
   npm install -g agent-browser

2. 安装浏览器:
   agent-browser install

安装完成后即可使用浏览器工具。"""

    def __init__(self, mode_manager: Optional[AgentModeManager] = None, session_id: Optional[str] = None):
        super().__init__()
        self.mode_manager = mode_manager
        self.session_id = session_id or "default"

    @classmethod
    def check_agent_browser(cls) -> Tuple[bool, str]:
        """检查 agent-browser 是否可用

        Returns:
            (是否可用, 错误信息)
        """
        if cls._agent_browser_available is not None:
            if cls._agent_browser_available:
                return True, ""
            return False, cls._install_message

        try:
            result = subprocess.run(
                ["agent-browser", "--version"],
                capture_output=True,
                text=True,
                timeout=5
            )
            cls._agent_browser_available = result.returncode == 0
            if cls._agent_browser_available:
                return True, ""
            return False, cls._install_message
        except FileNotFoundError:
            cls._agent_browser_available = False
            return False, cls._install_message
        except subprocess.TimeoutExpired:
            cls._agent_browser_available = False
            return False, "检测 agent-browser 超时"
        except Exception as e:
            cls._agent_browser_available = False
            return False, f"检测 agent-browser 失败: {str(e)}"

    @classmethod
    def reset_availability_cache(cls):
        """重置可用性缓存（用于测试）"""
        cls._agent_browser_available = None

    async def run_browser_command(self, args: List[str], timeout: int = 30) -> Tuple[bool, str]:
        """执行 agent-browser 命令

        Args:
            args: 命令参数列表
            timeout: 超时时间（秒）

        Returns:
            (是否成功, 输出或错误信息)
        """
        available, error_msg = self.check_agent_browser()
        if not available:
            return False, error_msg

        cmd = ["agent-browser", "--session", self.session_id, "--json"] + args

        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )

            stdout, stderr = await asyncio.wait_for(
                process.communicate(),
                timeout=timeout
            )

            stdout_str = stdout.decode('utf-8', errors='replace').strip()
            stderr_str = stderr.decode('utf-8', errors='replace').strip()

            if process.returncode == 0:
                return True, stdout_str
            else:
                return False, stderr_str or stdout_str or "命令执行失败"

        except asyncio.TimeoutError:
            return False, f"命令执行超时（{timeout}秒）"
        except Exception as e:
            return False, f"命令执行失败: {str(e)}"

    def invoke(self, inputs: dict, **kwargs) -> str:
        """同步调用"""
        return asyncio.run(self.ainvoke(inputs, **kwargs))


# ==================== BrowserOpenTool ====================

class BrowserOpenTool(BrowserToolBase):
    """打开网页工具

    导航到指定 URL 的网页。
    """

    def __init__(self, mode_manager: Optional[AgentModeManager] = None, session_id: Optional[str] = None):
        super().__init__(mode_manager, session_id)
        self.name = "browser_open"
        self.description = """打开指定 URL 的网页。

使用说明:
- 用于导航到指定网页
- 会等待页面加载完成
- 所有模式下可用

参数:
- url: 要打开的网页地址（必需）
"""
        self.params = [
            Param(name="url", description="要打开的网页地址", param_type="string", required=True),
        ]

    async def ainvoke(self, inputs: dict, **kwargs) -> str:
        """异步调用"""
        url = inputs.get("url", "")
        if not url:
            return "错误: 未指定 URL"

        success, result = await self.run_browser_command(["open", url], timeout=60)
        if success:
            return f"已打开网页: {url}"
        return f"错误: {result}"

    def get_tool_info(self) -> ToolInfo:
        """获取工具信息"""
        return ToolInfo(
            type="function",
            name=self.name,
            description=self.description,
            parameters=Parameters(
                type="object",
                properties={
                    "url": {"type": "string", "description": "要打开的网页地址"}
                },
                required=["url"]
            )
        )


# ==================== BrowserSnapshotTool ====================

class BrowserSnapshotTool(BrowserToolBase):
    """获取页面快照工具

    获取当前页面的可访问性树快照，返回元素及其引用标识。
    """

    def __init__(self, mode_manager: Optional[AgentModeManager] = None, session_id: Optional[str] = None):
        super().__init__(mode_manager, session_id)
        self.name = "browser_snapshot"
        self.description = """获取当前页面的可访问性树快照。

使用说明:
- 返回页面元素及其引用标识（如 @e1, @e2）
- 默认只返回可交互元素，设置 full=true 返回完整快照
- 使用返回的引用标识进行后续操作（click, fill 等）

参数:
- full: 是否返回完整快照（默认 false，只返回可交互元素）
"""
        self.params = [
            Param(name="full", description="是否返回完整快照", param_type="boolean", required=False, default_value=False),
        ]

    async def ainvoke(self, inputs: dict, **kwargs) -> str:
        """异步调用"""
        full = inputs.get("full", False)

        args = ["snapshot"]
        if not full:
            args.append("-i")  # 只返回可交互元素

        success, result = await self.run_browser_command(args)
        if success:
            # 截断过长的结果以避免 API 400 错误
            # 保留前 8000 字符，这样可以保留足够的上下文
            # 同时避免消息体过大导致 API 错误
            MAX_LENGTH = 8000
            if len(result) > MAX_LENGTH:
                truncated_result = result[:MAX_LENGTH]
                truncated_result += f"\n\n... [结果过长，已截断 {len(result) - MAX_LENGTH} 字符]"
                return truncated_result
            return result
        return f"错误: {result}"

    def get_tool_info(self) -> ToolInfo:
        """获取工具信息"""
        return ToolInfo(
            type="function",
            name=self.name,
            description=self.description,
            parameters=Parameters(
                type="object",
                properties={
                    "full": {"type": "boolean", "description": "是否返回完整快照"}
                },
                required=[]
            )
        )


# ==================== BrowserClickTool ====================

class BrowserClickTool(BrowserToolBase):
    """点击元素工具

    点击页面上的指定元素。仅在 BUILD 模式下可用。
    """

    def __init__(self, mode_manager: Optional[AgentModeManager] = None, session_id: Optional[str] = None):
        super().__init__(mode_manager, session_id)
        self.name = "browser_click"
        self.description = """点击页面元素。

使用说明:
- 使用 snapshot 返回的引用标识（如 @e1）指定元素
- 仅在 BUILD 模式下可用

参数:
- ref: 元素引用标识（如 @e1）（必需）
"""
        self.params = [
            Param(name="ref", description="元素引用标识（如 @e1）", param_type="string", required=True),
        ]

    async def ainvoke(self, inputs: dict, **kwargs) -> str:
        """异步调用"""
        # 模式检查
        if self.mode_manager and self.mode_manager.get_current_mode() != AgentMode.BUILD:
            return f"错误: browser_click 在 {self.mode_manager.get_current_mode().value} 模式下不可用。请切换到 BUILD 模式。"

        ref = inputs.get("ref", "")
        if not ref:
            return "错误: 未指定元素引用"

        success, result = await self.run_browser_command(["click", ref])
        if success:
            return f"已点击元素: {ref}"
        return f"错误: {result}"

    def get_tool_info(self) -> ToolInfo:
        """获取工具信息"""
        return ToolInfo(
            type="function",
            name=self.name,
            description=self.description,
            parameters=Parameters(
                type="object",
                properties={
                    "ref": {"type": "string", "description": "元素引用标识（如 @e1）"}
                },
                required=["ref"]
            )
        )


# ==================== BrowserFillTool ====================

class BrowserFillTool(BrowserToolBase):
    """填写输入框工具

    填写输入框（会先清空原有内容）。仅在 BUILD 模式下可用。
    """

    def __init__(self, mode_manager: Optional[AgentModeManager] = None, session_id: Optional[str] = None):
        super().__init__(mode_manager, session_id)
        self.name = "browser_fill"
        self.description = """填写输入框（会先清空原有内容）。

使用说明:
- 使用 snapshot 返回的引用标识指定输入框
- 会先清空输入框再填写新内容
- 仅在 BUILD 模式下可用

参数:
- ref: 输入框引用标识（如 @e3）（必需）
- text: 要填写的文本（必需）
"""
        self.params = [
            Param(name="ref", description="输入框引用标识", param_type="string", required=True),
            Param(name="text", description="要填写的文本", param_type="string", required=True),
        ]

    async def ainvoke(self, inputs: dict, **kwargs) -> str:
        """异步调用"""
        # 模式检查
        if self.mode_manager and self.mode_manager.get_current_mode() != AgentMode.BUILD:
            return f"错误: browser_fill 在 {self.mode_manager.get_current_mode().value} 模式下不可用。请切换到 BUILD 模式。"

        ref = inputs.get("ref", "")
        text = inputs.get("text", "")

        if not ref:
            return "错误: 未指定输入框引用"
        if not text:
            return "错误: 未指定填写文本"

        success, result = await self.run_browser_command(["fill", ref, text])
        if success:
            return f"已填写 {ref}: {text}"
        return f"错误: {result}"

    def get_tool_info(self) -> ToolInfo:
        """获取工具信息"""
        return ToolInfo(
            type="function",
            name=self.name,
            description=self.description,
            parameters=Parameters(
                type="object",
                properties={
                    "ref": {"type": "string", "description": "输入框引用标识"},
                    "text": {"type": "string", "description": "要填写的文本"}
                },
                required=["ref", "text"]
            )
        )


# ==================== BrowserTypeTool ====================

class BrowserTypeTool(BrowserToolBase):
    """键入文本工具

    在元素中键入文本（不清空原有内容）。仅在 BUILD 模式下可用。
    """

    def __init__(self, mode_manager: Optional[AgentModeManager] = None, session_id: Optional[str] = None):
        super().__init__(mode_manager, session_id)
        self.name = "browser_type"
        self.description = """在元素中键入文本（不清空原有内容）。

使用说明:
- 与 fill 不同，type 不会清空原有内容
- 仅在 BUILD 模式下可用

参数:
- ref: 元素引用标识（必需）
- text: 要键入的文本（必需）
"""
        self.params = [
            Param(name="ref", description="元素引用标识", param_type="string", required=True),
            Param(name="text", description="要键入的文本", param_type="string", required=True),
        ]

    async def ainvoke(self, inputs: dict, **kwargs) -> str:
        """异步调用"""
        # 模式检查
        if self.mode_manager and self.mode_manager.get_current_mode() != AgentMode.BUILD:
            return f"错误: browser_type 在 {self.mode_manager.get_current_mode().value} 模式下不可用。请切换到 BUILD 模式。"

        ref = inputs.get("ref", "")
        text = inputs.get("text", "")

        if not ref:
            return "错误: 未指定元素引用"

        success, result = await self.run_browser_command(["type", ref, text])
        if success:
            return f"已在 {ref} 键入文本"
        return f"错误: {result}"

    def get_tool_info(self) -> ToolInfo:
        """获取工具信息"""
        return ToolInfo(
            type="function",
            name=self.name,
            description=self.description,
            parameters=Parameters(
                type="object",
                properties={
                    "ref": {"type": "string", "description": "元素引用标识"},
                    "text": {"type": "string", "description": "要键入的文本"}
                },
                required=["ref", "text"]
            )
        )


# ==================== BrowserScreenshotTool ====================

class BrowserScreenshotTool(BrowserToolBase):
    """截图工具

    截取当前页面截图。
    """

    def __init__(self, mode_manager: Optional[AgentModeManager] = None, session_id: Optional[str] = None):
        super().__init__(mode_manager, session_id)
        self.name = "browser_screenshot"
        self.description = """截取当前页面截图。

使用说明:
- 可指定保存路径，不指定则保存到临时目录
- 所有模式下可用

参数:
- path: 截图保存路径（可选）
"""
        self.params = [
            Param(name="path", description="截图保存路径", param_type="string", required=False),
        ]

    async def ainvoke(self, inputs: dict, **kwargs) -> str:
        """异步调用"""
        import time
        from ..media.media_manager import MediaManager

        path = inputs.get("path", "")

        # 如果未指定路径，使用媒体目录
        if not path:
            session_id = self.session_id or "default"
            media_dir = MediaManager.get_output_dir(session_id)
            timestamp = int(time.time())
            path = os.path.join(media_dir, f"screenshot_{timestamp}.png")

        args = ["screenshot", path]

        success, result = await self.run_browser_command(args)
        if success:
            # 解析 JSON 结果获取实际路径
            try:
                import json
                data = json.loads(result)
                if data.get("success") and data.get("data"):
                    actual_path = data['data']
                    return f"截图已保存\nMEDIA:{actual_path}"
            except (json.JSONDecodeError, KeyError):
                pass
            return f"截图已保存\nMEDIA:{path}"
        return f"错误: {result}"

    def get_tool_info(self) -> ToolInfo:
        """获取工具信息"""
        return ToolInfo(
            type="function",
            name=self.name,
            description=self.description,
            parameters=Parameters(
                type="object",
                properties={
                    "path": {"type": "string", "description": "截图保存路径"}
                },
                required=[]
            )
        )


# ==================== BrowserScrollTool ====================

class BrowserScrollTool(BrowserToolBase):
    """滚动页面工具

    滚动页面。
    """

    def __init__(self, mode_manager: Optional[AgentModeManager] = None, session_id: Optional[str] = None):
        super().__init__(mode_manager, session_id)
        self.name = "browser_scroll"
        self.description = """滚动页面。

使用说明:
- 支持四个方向: up, down, left, right
- 可指定滚动像素数
- 所有模式下可用

参数:
- direction: 滚动方向（up/down/left/right）（必需）
- pixels: 滚动像素数（默认 500）
"""
        self.params = [
            Param(name="direction", description="滚动方向", param_type="string", required=True),
            Param(name="pixels", description="滚动像素数", param_type="integer", required=False, default_value=500),
        ]

    async def ainvoke(self, inputs: dict, **kwargs) -> str:
        """异步调用"""
        direction = inputs.get("direction", "")
        pixels = inputs.get("pixels", 500)

        if direction not in ["up", "down", "left", "right"]:
            return "错误: direction 必须是 up/down/left/right"

        success, result = await self.run_browser_command(["scroll", direction, str(pixels)])
        if success:
            return f"已向 {direction} 滚动 {pixels} 像素"
        return f"错误: {result}"

    def get_tool_info(self) -> ToolInfo:
        """获取工具信息"""
        return ToolInfo(
            type="function",
            name=self.name,
            description=self.description,
            parameters=Parameters(
                type="object",
                properties={
                    "direction": {"type": "string", "description": "滚动方向（up/down/left/right）"},
                    "pixels": {"type": "integer", "description": "滚动像素数"}
                },
                required=["direction"]
            )
        )


# ==================== BrowserWaitTool ====================

class BrowserWaitTool(BrowserToolBase):
    """等待条件工具

    等待指定条件满足。
    """

    def __init__(self, mode_manager: Optional[AgentModeManager] = None, session_id: Optional[str] = None):
        super().__init__(mode_manager, session_id)
        self.name = "browser_wait"
        self.description = """等待指定条件满足。

使用说明:
- 可等待元素出现、文本出现或指定时间
- 三个参数只需指定一个
- 所有模式下可用

参数:
- selector: 等待元素出现（CSS 选择器或引用）
- text: 等待文本出现
- ms: 等待指定毫秒数
"""
        self.params = [
            Param(name="selector", description="等待元素出现", param_type="string", required=False),
            Param(name="text", description="等待文本出现", param_type="string", required=False),
            Param(name="ms", description="等待毫秒数", param_type="integer", required=False),
        ]

    async def ainvoke(self, inputs: dict, **kwargs) -> str:
        """异步调用"""
        selector = inputs.get("selector")
        text = inputs.get("text")
        ms = inputs.get("ms")

        if selector:
            success, result = await self.run_browser_command(["wait", selector], timeout=60)
        elif text:
            success, result = await self.run_browser_command(["wait", "--text", text], timeout=60)
        elif ms:
            success, result = await self.run_browser_command(["wait", str(ms)], timeout=max(60, ms // 1000 + 10))
        else:
            return "错误: 请指定 selector、text 或 ms 参数"

        if success:
            return "等待完成"
        return f"错误: {result}"

    def get_tool_info(self) -> ToolInfo:
        """获取工具信息"""
        return ToolInfo(
            type="function",
            name=self.name,
            description=self.description,
            parameters=Parameters(
                type="object",
                properties={
                    "selector": {"type": "string", "description": "等待元素出现（CSS 选择器或引用）"},
                    "text": {"type": "string", "description": "等待文本出现"},
                    "ms": {"type": "integer", "description": "等待毫秒数"}
                },
                required=[]
            )
        )


# ==================== 工具工厂 ====================

def create_browser_tools(
    mode_manager: Optional[AgentModeManager] = None,
    session_id: Optional[str] = None
) -> List[Tool]:
    """创建所有浏览器工具

    Args:
        mode_manager: 模式管理器（可选）
        session_id: 会话 ID（可选，用于浏览器会话隔离）

    Returns:
        浏览器工具列表
    """
    return [
        BrowserOpenTool(mode_manager, session_id),
        BrowserSnapshotTool(mode_manager, session_id),
        BrowserClickTool(mode_manager, session_id),
        BrowserFillTool(mode_manager, session_id),
        BrowserTypeTool(mode_manager, session_id),
        BrowserScreenshotTool(mode_manager, session_id),
        BrowserScrollTool(mode_manager, session_id),
        BrowserWaitTool(mode_manager, session_id),
    ]
