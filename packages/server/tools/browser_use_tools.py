"""
browser-use 浏览器自动化工具

与现有 browser_tools.py (agent-browser) 共存，
提供 LLM 驱动的高级浏览器自动化能力。

特点:
- AI 驱动的智能浏览器操作
- 可视化弹窗模式 (headless=False)
- 自动完成复杂的多步骤任务
- Cookie 持久化支持（免登录）

依赖:
    pip install browser-use>=0.11.0

Cookie 持久化使用方式:
    1. 使用 user_data_dir: 复用已有浏览器配置（含登录状态）
    2. 使用 storage_state: 加载已保存的 cookies.json 文件

    # 方式1: 使用 Chrome 用户目录（自动继承登录状态）
    tool = BrowserUseTaskTool(
        user_data_dir="~/.config/google-chrome/Default"
    )

    # 方式2: 使用保存的 cookies 文件
    tool = BrowserUseTaskTool(
        storage_state="~/.lumos/browser_cookies.json"
    )
"""

import os
import json
import asyncio
from pathlib import Path
from typing import Optional, List, Tuple, Any, Union, Callable, Dict

)


from ..core.tool import Tool, ToolInfo, Parameters, Param

from ..agents.mode_manager import AgentModeManager, AgentMode


# ==================== 检测 browser-use 是否可用 ====================

_BROWSER_USE_AVAILABLE: Optional[bool] = None
_BROWSER_USE_ERROR: str = ""


def check_browser_use_available() -> Tuple[bool, str]:
    """检查 browser-use 是否可用"""
    global _BROWSER_USE_AVAILABLE, _BROWSER_USE_ERROR

    if _BROWSER_USE_AVAILABLE is not None:
        return _BROWSER_USE_AVAILABLE, _BROWSER_USE_ERROR

    try:
        from browser_use import Agent, Browser
        _BROWSER_USE_AVAILABLE = True
        _BROWSER_USE_ERROR = ""
        return True, ""
    except ImportError as e:
        _BROWSER_USE_AVAILABLE = False
        _BROWSER_USE_ERROR = f"""browser-use 未安装。请执行以下命令安装：

pip install browser-use>=0.11.0

安装 Chromium 浏览器：
python -c "from browser_use import Browser; Browser().install()"

错误详情: {str(e)}"""
        return False, _BROWSER_USE_ERROR


# ==================== BrowserUseTaskTool ====================

class BrowserUseTaskTool(Tool):
    """AI 驱动的浏览器任务工具

    使用 browser-use 库执行复杂的浏览器自动化任务。
    支持可视化弹窗模式，用户可实时观看操作过程。
    支持 Cookie 持久化，免登录访问已认证网站。
    """

    # 默认 cookie 存储路径
    DEFAULT_COOKIES_PATH = "~/.lumos/browser_cookies.json"

    # 子任务事件回调类型
    SubtaskEventCallback = Callable[[Dict[str, Any]], Any]

    def __init__(
        self,
        mode_manager: Optional[AgentModeManager] = None,
        session_id: Optional[str] = None,
        headless: bool = False,
        window_width: int = 1440,
        window_height: int = 900,
        user_data_dir: Optional[str] = None,
        storage_state: Optional[Union[str, Path, dict]] = None,
        save_cookies_on_close: bool = True,
        subtask_event_callback: Optional["BrowserUseTaskTool.SubtaskEventCallback"] = None,
        ws_manager=None
    ):
        """初始化工具

        Args:
            mode_manager: 模式管理器
            session_id: 会话 ID
            headless: 是否无头模式（默认 False，弹出可视化窗口）
            window_width: 窗口宽度（默认 1440）
            window_height: 窗口高度（默认 900）
            user_data_dir: Chrome 用户数据目录（复用已有登录状态）
            storage_state: Cookie 状态文件路径或 dict（会自动加载）
            save_cookies_on_close: 任务完成后是否保存 cookies（默认 True）
            subtask_event_callback: 子任务事件回调（用于实时进度更新）
            ws_manager: WebSocket 管理器（用于广播事件）
        """
        super().__init__()
        self.mode_manager = mode_manager
        self.session_id = session_id or "default"
        self.headless = headless
        self.window_width = window_width
        self.window_height = window_height
        self.user_data_dir = user_data_dir
        self.storage_state = storage_state
        self.save_cookies_on_close = save_cookies_on_close
        self._subtask_event_callback = subtask_event_callback
        self._ws_manager = ws_manager

        self.name = "browser_use_task"
        self.description = """使用 AI 驱动的浏览器执行复杂任务。

使用说明:
- 适合需要多步骤操作的复杂任务（如"登录并填写表单"）
- 浏览器会弹出可视化窗口，可实时观看操作过程
- AI 会自动规划和执行操作步骤
- 仅在 BUILD 模式下可用

参数:
- task: 要执行的任务描述（必需，如"登录腾讯文档并在表格中填入发票数据"）
- url: 起始 URL（可选，如不指定则从空白页开始）
- max_steps: 最大操作步骤数（可选，默认 50）

示例:
- task: "登录 https://docs.qq.com 并在第一个表格中填入以下数据..."
- task: "打开百度搜索 Python 教程，点击第一个结果"
"""
        self.params = [
            Param(
                name="task",
                description="要执行的任务描述",
                param_type="string",
                required=True
            ),
            Param(
                name="url",
                description="起始 URL（可选）",
                param_type="string",
                required=False
            ),
            Param(
                name="max_steps",
                description="最大操作步骤数",
                param_type="integer",
                required=False,
                default_value=50
            ),
        ]

    async def ainvoke(self, inputs: dict, **kwargs) -> str:
        """异步执行任务"""
        # 清除代理环境变量（browser-use 不支持 socks 代理）
        self._clear_proxy_env()

        # 检查 browser-use 是否可用
        available, error_msg = check_browser_use_available()
        if not available:
            return f"错误: {error_msg}"

        # 模式检查
        if (self.mode_manager and
                self.mode_manager.get_current_mode() != AgentMode.BUILD):
            mode = self.mode_manager.get_current_mode().value
            return (
                f"错误: browser_use_task 在 {mode} 模式下不可用。"
                f"请切换到 BUILD 模式。"
            )

        task = inputs.get("task", "")
        if not task:
            return "错误: 未指定任务描述"

        url = inputs.get("url", "")
        max_steps = inputs.get("max_steps", 50)

        try:
            from browser_use import Agent, Browser

            # 准备浏览器配置
            browser_kwargs = {
                "headless": self.headless,
                "window_size": {
                    "width": self.window_width,
                    "height": self.window_height
                },
            }

            # 添加用户数据目录（复用已有浏览器配置）
            if self.user_data_dir:
                user_data_path = os.path.expanduser(self.user_data_dir)
                if os.path.exists(user_data_path):
                    browser_kwargs["user_data_dir"] = user_data_path

            # 加载已保存的 cookies（storage_state）
            storage_state = self._load_storage_state()
            if storage_state:
                browser_kwargs["storage_state"] = storage_state

            # 创建浏览器实例
            browser = Browser(**browser_kwargs)

            # 获取 LLM 配置
            llm = self._get_llm()

            # 发送任务开始事件
            self._emit_step_event_sync(
                step_num=0,
                goal=f"启动浏览器任务: {task[:50]}...",
                action="正在启动浏览器...",
                status="starting"
            )

            # 收集步骤信息
            step_logs = []

            def on_step(browser_state, agent_output, step_num):
                """步骤回调：记录每一步的操作并发送实时更新"""
                step_info = f"📍 步骤 {step_num}:"
                goal = ""
                action_desc = ""

                # 提取目标
                if hasattr(agent_output, 'current_state'):
                    state = agent_output.current_state
                    if hasattr(state, 'next_goal') and state.next_goal:
                        goal = state.next_goal
                        step_info += f"\n   🎯 目标: {goal}"

                # 提取动作
                if hasattr(agent_output, 'action') and agent_output.action:
                    actions = agent_output.action
                    if isinstance(actions, list):
                        for i, act in enumerate(actions):
                            act_desc = self._format_action(act)
                            step_info += f"\n   ▶️ [{i+1}] {act_desc}"
                            action_desc += f"[{i+1}] {act_desc} "
                    else:
                        act_desc = self._format_action(actions)
                        step_info += f"\n   ▶️ {act_desc}"
                        action_desc = act_desc

                step_logs.append(step_info)

                # 发送实时进度更新到前端
                self._emit_step_event_sync(
                    step_num=step_num,
                    goal=goal,
                    action=action_desc.strip(),
                    status="running"
                )

            # 创建 Agent
            agent = Agent(
                task=task,
                llm=llm,
                browser=browser,
                max_actions_per_step=max_steps,
                register_new_step_callback=on_step,
            )

            # 如果指定了 URL，先导航到该页面
            if url:
                await agent.browser_session.navigate_to(url)

            # 执行任务
            history = await agent.run()

            # 返回结果
            result_parts = ["✅ 任务执行完成"]

            # 添加步骤详情
            if step_logs:
                result_parts.append("\n\n📋 执行步骤:")
                result_parts.extend(step_logs)

            # 提取最终结果
            if history and hasattr(history, 'final_result'):
                final = history.final_result()
                if final:
                    result_parts.append(f"\n\n📄 最终结果:\n{final}")

            if history:
                result_parts.append(f"\n\n共执行了 {len(history)} 个操作步骤")

            # 保存 cookies（如果启用）
            if self.save_cookies_on_close:
                save_result = await self._save_storage_state(agent)
                if save_result:
                    result_parts.append(f"\n\n🍪 {save_result}")

            # 关闭 Agent（会自动关闭浏览器）
            await agent.close()

            return "\n".join(result_parts)

        except Exception as e:
            return f"错误: 浏览器任务执行失败 - {str(e)}"

    def _emit_step_event_sync(
        self,
        step_num: int,
        goal: str,
        action: str,
        status: str = "running"
    ):
        """同步发送步骤事件（在回调中使用）

        Args:
            step_num: 步骤编号
            goal: 当前目标
            action: 执行的动作
            status: 状态（running/completed/error）
        """
        # 映射状态到前端期望的格式
        status_map = {
            "starting": "starting",
            "running": "tool_call",
            "completed": "completed",
            "error": "error"
        }

        # 构造符合前端 SubtaskUpdatePayload 格式的事件
        event_data = {
            "task_id": f"browser_step_{step_num}",
            "description": goal or f"浏览器操作步骤 {step_num}",
            "status": status_map.get(status, "tool_call"),
            "index": step_num - 1,  # 前端使用 0-based index
            "total": 50,  # 估计总步骤数
            "tool_name": "browser_use_task",
            "tool_count": step_num,
            "message": action or "执行中...",
            "is_parallel": False,
            # 额外的浏览器相关信息
            "browser_goal": goal,
            "browser_action": action
        }

        # 通过 WebSocket 广播实时更新
        if self._ws_manager:
            try:
                # 使用 asyncio 在同步回调中发送异步事件
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    asyncio.create_task(
                        self._ws_manager.broadcast_agent_event(
                            self.session_id,
                            "subtask_update",
                            event_data
                        )
                    )
            except Exception:
                pass  # 忽略广播错误，不影响主流程

        # 同时调用回调（如果有）
        if self._subtask_event_callback:
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    asyncio.create_task(
                        self._async_emit_callback(event_data)
                    )
            except Exception:
                pass

    async def _async_emit_callback(self, event_data: Dict[str, Any]):
        """异步发送事件到回调"""
        if self._subtask_event_callback:
            try:
                result = self._subtask_event_callback(event_data)
                if asyncio.iscoroutine(result):
                    await result
            except Exception:
                pass

    async def _emit_subtask_event(self, event_data: Dict[str, Any]):
        """发送子任务事件到回调（异步版本）"""
        if self._subtask_event_callback:
            try:
                result = self._subtask_event_callback(event_data)
                if asyncio.iscoroutine(result):
                    await result
            except Exception as e:
                print(f"[BrowserUse] 子任务事件回调错误: {e}")

    def _load_storage_state(self) -> Optional[Union[str, dict]]:
        """加载已保存的 cookie 状态

        优先级：
        1. 传入的 storage_state 参数
        2. 默认路径 ~/.lumos/browser_cookies.json

        Returns:
            storage_state 路径或 dict，无则返回 None
        """
        # 如果直接传入了 storage_state
        if self.storage_state:
            if isinstance(self.storage_state, dict):
                return self.storage_state
            state_path = os.path.expanduser(str(self.storage_state))
            if os.path.exists(state_path):
                return state_path

        # 尝试加载默认路径
        default_path = os.path.expanduser(self.DEFAULT_COOKIES_PATH)
        if os.path.exists(default_path):
            return default_path

        return None

    async def _save_storage_state(self, agent) -> Optional[str]:
        """保存当前浏览器的 cookie 状态

        使用 browser-use 的 export_storage_state 方法保存 cookies。

        Args:
            agent: browser-use Agent 实例

        Returns:
            保存结果消息，失败返回 None
        """
        try:
            # 获取浏览器 session
            if not hasattr(agent, 'browser_session'):
                print("[BrowserUse] 无法保存 cookies: agent 没有 browser_session")
                return None

            session = agent.browser_session
            if session is None:
                print("[BrowserUse] 无法保存 cookies: browser_session 为 None")
                return None

            # 确定保存路径
            if self.storage_state and isinstance(self.storage_state, str):
                save_path = os.path.expanduser(self.storage_state)
            else:
                save_path = os.path.expanduser(self.DEFAULT_COOKIES_PATH)

            # 确保目录存在
            save_dir = os.path.dirname(save_path)
            if save_dir:
                os.makedirs(save_dir, exist_ok=True)

            # 使用 browser-use 的 export_storage_state 方法
            # 这个方法通过 CDP 获取解密的 cookies
            if hasattr(session, 'export_storage_state'):
                storage_state = await session.export_storage_state(save_path)
                cookie_count = len(storage_state.get('cookies', []))
                print(f"[BrowserUse] ✅ 已保存 {cookie_count} 个 cookies")
                return f"已保存 {cookie_count} 个 cookies 到 {save_path}"
            else:
                print("[BrowserUse] session 没有 export_storage_state 方法")
                return None

        except Exception as e:
            # 打印错误以便调试
            print(f"[BrowserUse] 保存 cookies 失败: {e}")
            return None

    def _format_action(self, action) -> str:
        """格式化动作信息为可读字符串"""
        # 获取动作类型名
        act_type = type(action).__name__.replace('ActionModel', '')

        # 尝试提取动作详情
        details = []

        # 常见动作属性
        if hasattr(action, 'url') and action.url:
            details.append(f"url={action.url}")
        if hasattr(action, 'index') and action.index is not None:
            details.append(f"index={action.index}")
        if hasattr(action, 'text') and action.text:
            text = action.text[:30] + "..." if len(
                action.text
            ) > 30 else action.text
            details.append(f"text='{text}'")
        if hasattr(action, 'success') and action.success is not None:
            details.append(f"success={action.success}")

        if details:
            return f"{act_type}({', '.join(details)})"
        return act_type or "unknown"

    def _load_config_file(self) -> dict:
        """加载配置文件 ~/.lumos/config.yaml"""
        import os
        config_path = os.path.expanduser("~/.lumos/config.yaml")
        if os.path.exists(config_path):
            try:
                import yaml
                with open(config_path, 'r') as f:
                    return yaml.safe_load(f) or {}
            except Exception:
                pass
        return {}

    def _clear_proxy_env(self):
        """清除代理环境变量（langchain_openai 不支持 socks 代理）"""
        import os
        proxy_keys = [
            'http_proxy', 'https_proxy', 'HTTP_PROXY',
            'HTTPS_PROXY', 'all_proxy', 'ALL_PROXY'
        ]
        for key in proxy_keys:
            os.environ.pop(key, None)

    def _get_llm(self) -> Any:
        """获取 LLM 实例

        使用 browser-use 自带的 ChatOpenAI（支持 OpenRouter）
        优先从配置文件读取，其次从环境变量
        """
        import os

        # 清除代理环境变量，避免 socks 代理冲突
        self._clear_proxy_env()

        # 使用 browser-use 自带的 ChatOpenAI
        from browser_use.llm import ChatOpenAI

        # 先从配置文件读取
        config = self._load_config_file()
        provider = config.get("provider", "").lower()
        api_key = config.get("api_key")
        api_base = config.get("api_base_url")
        model = config.get("model")

        # 如果配置文件有 OpenRouter 配置
        # 注意：browser-use 不支持 Opus 4.5 的结构化输出格式，使用 Sonnet 4
        if provider == "openrouter" and api_key:
            # 如果用户配置了 opus-4.5，自动降级到 sonnet-4
            browser_model = model
            if model and "opus" in model.lower():
                browser_model = "anthropic/claude-sonnet-4"
            return ChatOpenAI(
                model=browser_model or "anthropic/claude-sonnet-4",
                api_key=api_key,
                base_url=api_base or "https://openrouter.ai/api/v1",
                temperature=0.2,
            )

        # 从环境变量尝试 OpenRouter
        openrouter_key = os.environ.get("OPENROUTER_API_KEY")
        if openrouter_key:
            return ChatOpenAI(
                model="anthropic/claude-sonnet-4",
                api_key=openrouter_key,
                base_url="https://openrouter.ai/api/v1",
                temperature=0.2,
            )

        # 尝试使用 Anthropic（通过 OpenRouter 格式）
        anthropic_key = os.environ.get("ANTHROPIC_API_KEY")
        if anthropic_key:
            return ChatOpenAI(
                model="claude-sonnet-4-20250514",
                api_key=anthropic_key,
                base_url="https://api.anthropic.com/v1",
                temperature=0.2,
            )

        # 尝试使用 OpenAI
        openai_key = os.environ.get("OPENAI_API_KEY")
        if openai_key:
            return ChatOpenAI(
                model="gpt-4o",
                api_key=openai_key,
                temperature=0.2,
            )

        # 尝试使用智谱（兼容 OpenAI 格式）
        zhipu_key = os.environ.get("ZHIPU_API_KEY")
        if zhipu_key:
            return ChatOpenAI(
                model="glm-4-plus",
                api_key=zhipu_key,
                base_url="https://open.bigmodel.cn/api/paas/v4",
                temperature=0.2,
            )

        raise ValueError(
            "未找到可用的 LLM。"
            "请在 ~/.lumos/config.yaml 配置或设置环境变量 "
            "OPENROUTER_API_KEY、ANTHROPIC_API_KEY、"
            "OPENAI_API_KEY 或 ZHIPU_API_KEY"
        )

    def invoke(self, inputs: dict, **kwargs) -> str:
        """同步调用"""
        return asyncio.run(self.ainvoke(inputs, **kwargs))

    def get_tool_info(self) -> ToolInfo:
        """获取工具信息"""
        return ToolInfo(
            type="function",
            name=self.name,
            description=self.description,
            parameters=Parameters(
                type="object",
                properties={
                    "task": {
                        "type": "string",
                        "description": "要执行的任务描述"
                    },
                    "url": {
                        "type": "string",
                        "description": "起始 URL（可选）"
                    },
                    "max_steps": {
                        "type": "integer",
                        "description": "最大操作步骤数（默认 50）"
                    }
                },
                required=["task"]
            )
        )


# ==================== BrowserUseNavigateTool ====================

class BrowserUseNavigateTool(Tool):
    """browser-use 导航工具

    使用 browser-use 打开指定 URL。
    支持 Cookie 持久化，免登录访问已认证网站。
    """

    # 默认 cookie 存储路径
    DEFAULT_COOKIES_PATH = "~/.lumos/browser_cookies.json"

    def __init__(
        self,
        mode_manager: Optional[AgentModeManager] = None,
        session_id: Optional[str] = None,
        headless: bool = False,
        window_width: int = 1440,
        window_height: int = 900,
        user_data_dir: Optional[str] = None,
        storage_state: Optional[Union[str, Path, dict]] = None
    ):
        super().__init__()
        self.mode_manager = mode_manager
        self.session_id = session_id or "default"
        self.headless = headless
        self.window_width = window_width
        self.window_height = window_height
        self.user_data_dir = user_data_dir
        self.storage_state = storage_state
        self._browser = None

        self.name = "browser_use_navigate"
        self.description = """使用 browser-use 打开指定网页。

使用说明:
- 打开指定 URL 的网页
- 浏览器窗口会弹出显示

参数:
- url: 要打开的网页地址（必需）
"""
        self.params = [
            Param(
                name="url",
                description="要打开的网页地址",
                param_type="string",
                required=True
            ),
        ]

    async def ainvoke(self, inputs: dict, **kwargs) -> str:
        """异步调用"""
        available, error_msg = check_browser_use_available()
        if not available:
            return f"错误: {error_msg}"

        url = inputs.get("url", "")
        if not url:
            return "错误: 未指定 URL"

        try:
            from browser_use import Browser

            # 准备浏览器配置
            browser_kwargs = {
                "headless": self.headless,
                "window_size": {
                    "width": self.window_width,
                    "height": self.window_height
                },
            }

            # 添加用户数据目录
            if self.user_data_dir:
                user_data_path = os.path.expanduser(self.user_data_dir)
                if os.path.exists(user_data_path):
                    browser_kwargs["user_data_dir"] = user_data_path

            # 加载已保存的 cookies
            storage_state = self._load_storage_state()
            if storage_state:
                browser_kwargs["storage_state"] = storage_state

            browser = Browser(**browser_kwargs)
            context = await browser.new_context()
            page = await context.new_page()
            await page.goto(url)

            # 保存引用以便后续操作
            self._browser = browser
            self._page = page

            # 提示是否加载了 cookies
            cookie_msg = ""
            if storage_state:
                cookie_msg = "（已加载保存的登录状态）"

            return f"✅ 已打开网页: {url} {cookie_msg}"

        except Exception as e:
            return f"错误: 打开网页失败 - {str(e)}"

    def _load_storage_state(self) -> Optional[Union[str, dict]]:
        """加载已保存的 cookie 状态"""
        # 如果直接传入了 storage_state
        if self.storage_state:
            if isinstance(self.storage_state, dict):
                return self.storage_state
            state_path = os.path.expanduser(str(self.storage_state))
            if os.path.exists(state_path):
                return state_path

        # 尝试加载默认路径
        default_path = os.path.expanduser(self.DEFAULT_COOKIES_PATH)
        if os.path.exists(default_path):
            return default_path

        return None

    def invoke(self, inputs: dict, **kwargs) -> str:
        """同步调用"""
        return asyncio.run(self.ainvoke(inputs, **kwargs))

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
                        "description": "要打开的网页地址"
                    }
                },
                required=["url"]
            )
        )


# ==================== 工具工厂 ====================

def create_browser_use_tools(
    mode_manager: Optional[AgentModeManager] = None,
    session_id: Optional[str] = None,
    headless: bool = False,
    window_width: int = 1440,
    window_height: int = 900,
    user_data_dir: Optional[str] = None,
    storage_state: Optional[Union[str, Path, dict]] = None,
    save_cookies_on_close: bool = True,
    subtask_event_callback: Optional[
        BrowserUseTaskTool.SubtaskEventCallback
    ] = None,
    ws_manager=None
) -> List[Tool]:
    """创建 browser-use 工具列表

    Args:
        mode_manager: 模式管理器
        session_id: 会话 ID
        headless: 是否无头模式（默认 False，弹出可视化窗口）
        window_width: 窗口宽度（默认 1440）
        window_height: 窗口高度（默认 900）
        user_data_dir: Chrome 用户数据目录（复用已有登录状态）
        storage_state: Cookie 状态文件路径或 dict
        save_cookies_on_close: 任务完成后是否保存 cookies
        subtask_event_callback: 子任务事件回调（用于实时进度更新）
        ws_manager: WebSocket 管理器（用于广播实时事件到前端）

    Returns:
        browser-use 工具列表

    Cookie 持久化说明:
        1. 首次运行时，在弹出的浏览器中手动登录
        2. 任务完成后会自动保存 cookies 到 ~/.lumos/browser_cookies.json
        3. 下次运行时会自动加载已保存的 cookies，无需再次登录

    实时进度更新说明:
        传入 ws_manager 或 subtask_event_callback 可在前端实时显示：
        - 当前执行的步骤编号
        - 当前目标
        - 正在执行的动作
    """
    return [
        BrowserUseTaskTool(
            mode_manager=mode_manager,
            session_id=session_id,
            headless=headless,
            window_width=window_width,
            window_height=window_height,
            user_data_dir=user_data_dir,
            storage_state=storage_state,
            save_cookies_on_close=save_cookies_on_close,
            subtask_event_callback=subtask_event_callback,
            ws_manager=ws_manager
        ),
        BrowserUseNavigateTool(
            mode_manager=mode_manager,
            session_id=session_id,
            headless=headless,
            window_width=window_width,
            window_height=window_height,
            user_data_dir=user_data_dir,
            storage_state=storage_state
        ),
    ]
