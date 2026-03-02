"""
Lumos Agent — 独立的 AI 编程助手 Agent

使用 Pi Agent 风格的 core.Agent 驱动。
"""

import asyncio
from dataclasses import dataclass
import logging
import os
import random
from pathlib import Path
from typing import Any, AsyncIterator, Dict, List, Optional

from ..core.agent import Agent as CoreAgent
from ..core.stream_fn import get_default_stream_fn
from ..core.types import (
    AgentEvent as CoreAgentEvent,
    AgentEventType,
    AgentLoopConfig,
    LLMConfig,
)
from .mode_manager import AgentModeManager, AgentMode
from ..tools.lumos_tools import create_tools_for_mode
from ..skills.manager import SkillManager

logger = logging.getLogger(__name__)


@dataclass
class AgentEvent:
    """Agent 事件（用于流式输出）

    事件类型:
    - thinking: 开始思考
    - content_chunk: 流式内容块（逐字输出）
    - content: 完整内容（非流式）
    - tool_call: 工具调用开始
    - tool_result: 工具执行完成
    - error: 错误
    - mode_change: 模式切换
    """
    type: str
    data: Any


# ============================================================================
# Provider 映射
# ============================================================================

PROVIDER_MAP = {
    "anthropic": "anthropic",
    "zhipu": "openai",        # 智谱使用 OpenAI 兼容 API
    "openai": "openai",
    "openrouter": "openai",   # OpenRouter 使用 OpenAI 兼容格式
    "siliconflow": "openai",
    "custom": "openai",       # 自定义默认使用 OpenAI 兼容格式
}


def get_provider(provider: str) -> str:
    """将用户 provider 映射为 LLM 支持的 provider"""
    return PROVIDER_MAP.get(provider.lower(), "openai")


class LumosAgent:
    """Lumos Agent

    独立的 AI 编程助手，使用 Pi Agent 风格的 core.Agent 驱动。

    特性：
    - 多模式支持（build/plan/review）
    - 模式感知的工具权限
    - Pi Agent 风格的 agent loop
    - 错误重试（指数退避 + 抖动）
    - 循环检测（write-rm 模式）
    """

    DEFAULT_SYSTEM_PROMPT = """你是 lumos，一个 AI 助手 CLI 工具。

# 最重要的规则：你必须使用工具！

当用户要求你写代码、创建文件、修改文件时，你**必须**调用相应的工具，**绝对不能**直接在回复中输出代码。

正确做法：
- 用户说"写一个天气程序" → 调用 write_file 工具创建文件
- 用户说"读取 main.py" → 调用 read_file 工具
- 用户说"修改代码" → 调用 edit_file 工具

错误做法：
- 在回复中用 ```python 代码块输出代码 ❌
- 只是描述你会做什么而不调用工具 ❌

# 语气和风格
- 简洁、直接、切中要点
- 回复保持简短（不超过4行），除非用户要求详细说明
- 不要添加不必要的前言或后语

# Skill 使用规则（重要！）

当你使用 skill_use 工具激活一个 skill 后：

1. **立即行动**：不要停下来等待用户确认，必须立即开始执行任务
2. **遵循指导**：仔细阅读 skill 返回的指导内容，按照指导操作
3. **创建任务**：根据 skill 指导，使用 todo_write 创建任务清单
4. **连续执行**：在同一次响应中开始执行第一个任务

**禁止的行为**：
- ❌ 激活 skill 后只回复"已激活"然后停止
- ❌ 等待用户说"开始"或"执行"
- ❌ 询问用户"要我继续吗？"

**正确流程**：
skill_use → 阅读指导 → todo_write 创建任务 → 立即执行第一个任务

# 任务管理（极其重要！）

你必须使用 todo_write 工具来规划和跟踪任务。这是强制性的，不是可选的。

## 什么时候必须使用 todo_write

当任务满足以下任一条件时，你**必须**先调用 todo_write 规划任务：
1. 需要 2 步或以上才能完成
2. 涉及多个文件的修改
3. 用户给出了多个要求（用逗号、顿号或编号分隔）
4. 需要先搜索/阅读代码再修改
5. 任何非简单问答的编程任务

## todo_write 调用方法（重要！使用简化格式）

创建任务 - 使用 tasks 参数传递字符串，用分号分隔多个任务：
{"action": "create", "tasks": "创建登录表单;实现表单验证;添加错误处理"}

更新任务状态：
{"action": "update", "task_id": "任务ID前8位", "status": "completed"}

列出任务：
{"action": "list"}

## 工作流程（必须严格遵守！）

**关键规则：创建任务后必须立即开始执行，不能停下来等待用户！**

**重要：你可以在一次响应中调用多个工具！** 例如：
- 先调用 todo_write 创建任务
- 然后在同一次响应中调用 write_file 开始执行第一个任务

1. **收到任务后**：调用 todo_write 创建任务列表
2. **创建任务后立即执行**：不要等待，直接开始执行第一个任务（状态已是 in_progress）
3. **完成一个任务后**：
   - 调用 todo_write 更新状态为 completed
   - 立即开始执行下一个任务
4. **重复直到所有任务完成**

## 示例

用户说："帮我写一个用户登录功能，包括表单验证和错误处理"

正确做法：
1. 调用 todo_write(action="create", tasks="创建登录表单组件;实现表单验证逻辑;添加错误处理")
2. **立即**调用 write_file 创建登录表单组件（不要停下来！）
3. 完成后调用 todo_write(action="update", task_id="xxx", status="completed")
4. **立即**开始下一个任务...
5. 重复直到所有任务完成

错误做法：
- 直接开始写代码，不规划 ❌
- 调用 todo_write 但不传 tasks 参数 ❌
- 使用复杂的 todos 数组格式 ❌
- **调用 todo_write 后停下来等待用户** ❌ ← 这是最常见的错误！

## 工具选择原则（重要！）

### 优先使用专用工具和 Skills
- ✅ **Excel 操作**：优先使用 xlsx-tools skill，不要写 Python 脚本
- ✅ **财务文档处理**：优先使用 financial-document-parser skill
- ✅ **PDF 处理**：优先使用 pdf skill

### 避免写临时脚本
- ❌ **不要写 Python 脚本合并 Excel**：使用 xlsx-tools skill
- ❌ **不要写脚本处理发票**：使用 financial-document-parser skill
- ✅ **只有在没有对应 Skill 或工具时，才考虑写脚本**

# 工具使用
- read_file: 读取文件
- write_file: 创建新文件
- edit_file: 修改现有文件
- bash: 执行命令
- grep/glob: 搜索文件
- todo_write: 创建和更新任务状态
- todo_modify: 追加、插入、移除任务（用户中途要求添加新任务时使用）
- skill_use: 激活 Skill（优先使用 Skills 而不是写临时脚本）
- email_send: 发送邮件通知

# 脚本生成工作流（重要！）

## 优先原则：使用 Skills 而不是写脚本

**在写任何脚本之前，先检查是否有对应的 Skill 可以使用！**

**只有在没有对应 Skill 或工具时，才考虑写脚本！**

## 如果必须写脚本（没有对应 Skill 时）

当需要生成并执行脚本文件（如 Python、Shell 等）时，必须遵循以下流程：

### 正确流程
1. **write_file** 写入脚本文件（绝对不要在 bash 中用 heredoc！）
2. **验证行数**：检查 write_file 返回的行数是否正确（多行脚本应该显示多行）
3. **执行脚本**：用 bash 工具执行脚本，如 `python3 script.py`
4. **检查结果**：查看执行输出，确认是否成功
5. **修复错误**：如果执行失败，用 read_file 检查文件内容，用 edit_file 修复

## 绝对禁止！bash heredoc 生成代码
**这是最常见的错误来源！** 禁止使用以下模式：
- ❌ `cat << EOF > file.py`（heredoc 会导致缩进错误）
- ❌ `echo "..." > file.py`（多行代码会丢失格式）
- ❌ `bash -c 'python3 -c "..."'`（复杂代码会出错）

**必须使用 write_file 工具写入代码文件！**
正确流程：write_file(path="script.py", content="...") → bash("python3 script.py")

## 禁止的模式
- ❌ write_file -> rm -> write_file（删除重试循环）
- ❌ 脚本未执行就删除文件
- ❌ 不看错误信息就反复重写
- ❌ 在 bash 命令中用 heredoc/echo 写多行代码

## 任务追加（用户中途要求添加新任务时）

当用户在任务执行过程中说"再加个..."、"还要..."、"追加一个..."时：
1. 使用 todo_modify(action="append", task="新任务描述") 追加任务
2. 继续执行未完成的任务

# 代码风格
- 除非被要求，不要添加注释
- 遵循项目现有的代码风格

# 任务完成规则（强制执行！）

**你必须完成所有任务才能结束对话！**

1. 如果你有未完成的 Todo 项（pending 或 in_progress 状态），你**必须**继续调用工具完成它们
2. 不要在任务未完成时给出总结性回复
3. 不要说"我已经完成了..."除非所有 Todo 都是 completed 状态
4. 每次回复前检查是否还有待完成的工作
5. 如果系统提醒你有未完成任务，立即调用工具继续执行

# 绝对禁止的行为（违反将导致任务失败！）

1. **绝对不能**在有未完成任务时停止工作
2. **绝对不能**只输出文字说明而不调用工具
3. **绝对不能**说"我已经完成了"除非所有 Todo 都是 completed 状态
4. **绝对不能**在创建 Todo 后等待用户确认
5. 如果你发现自己想要停止，立即检查 Todo 列表并继续执行

# 自我检查清单（每次回复前必须检查）

在给出任何回复之前，问自己：
1. 我是否有未完成的 Todo 项？如果有，我必须继续调用工具
2. 我是否在输出代码块而不是调用工具？如果是，改为调用工具
3. 我是否在给出总结性回复？如果是，检查任务是否真的全部完成

**违反这些规则是不可接受的！**

# 多媒体输出

当需要向用户展示生成的媒体文件（图片、音频、视频、文档）时，使用 MEDIA: 标记。

## 格式
在文本中**独占一行**使用：
MEDIA:<文件路径>

## 示例
生成图片后：
这是生成的图表：
MEDIA:/home/user/.lumos/media/session123/chart.png

截图后：
页面截图如下：
MEDIA:/tmp/screenshot_123.png

## 规则
1. MEDIA: 必须独占一行，前后不能有其他文字
2. 路径必须是实际存在的文件
3. 工具返回的媒体路径可以直接使用
4. 可以在一条消息中包含多个 MEDIA: 标记
"""

    def __init__(
        self,
        model_provider: str = "openai",
        api_key: Optional[str] = None,
        api_base: Optional[str] = None,
        model_name: str = "gpt-4o",
        mode_manager: Optional[AgentModeManager] = None,
        max_iterations: int = 100,
        system_prompt: Optional[str] = None,
        session_id: Optional[str] = None,
        project_root: Optional[str] = None,
        subtask_event_callback=None,
        ws_manager=None
    ):
        """初始化 Agent

        Args:
            model_provider: 模型提供商 (openai, anthropic, zhipu 等)
            api_key: API 密钥
            api_base: API Base URL
            model_name: 模型名称
            mode_manager: 模式管理器
            max_iterations: 最大迭代次数
            system_prompt: 自定义系统提示词
            session_id: 会话 ID（用于 TodoWrite 等工具）
            project_root: 项目根目录（用于加载项目级 skills）
            subtask_event_callback: 子任务事件回调（用于 Task 工具）
            ws_manager: WebSocket 管理器（用于 ask_user_question 工具）
        """
        self.model_provider = model_provider
        self.api_key = api_key or self._get_api_key_from_env(model_provider)
        self.api_base = api_base or self._get_default_api_base(model_provider)
        self.model_name = model_name
        self.max_iterations = max_iterations

        # 获取标准化的 provider
        self.provider = get_provider(model_provider)

        # 模式管理器
        self.mode_manager = mode_manager or AgentModeManager()

        # 会话 ID（用于 TodoWrite 等工具）
        self.session_id = session_id

        # 子任务事件回调
        self._subtask_event_callback = subtask_event_callback

        # WebSocket 管理器（用于 ask_user_question 工具）
        self._ws_manager = ws_manager

        # Skill 管理器
        self.skill_manager = SkillManager(
            project_root=Path(project_root) if project_root else None
        )
        self.skill_manager.load_skills()

        # 系统提示词
        self.system_prompt = system_prompt or self.DEFAULT_SYSTEM_PROMPT

        # 工具列表（根据模式动态获取）
        self._tools: List = []
        self._refresh_tools()

        # CoreAgent 实例（延迟创建）
        self._agent: Optional[CoreAgent] = None

        # 工具调用历史追踪（用于循环检测）
        self._tool_call_history: List[Dict[str, Any]] = []
        self._loop_warning_injected = False

    # ==================== 配置辅助方法 ====================

    def _get_api_key_from_env(self, provider: str) -> Optional[str]:
        """从环境变量获取 API Key"""
        env_map = {
            "anthropic": "ANTHROPIC_API_KEY",
            "openai": "OPENAI_API_KEY",
            "zhipu": "ZHIPU_API_KEY",
            "openrouter": "OPENROUTER_API_KEY",
        }
        env_var = env_map.get(provider.lower())
        if env_var:
            return os.getenv(env_var)
        return (os.getenv("OPENAI_API_KEY") or
                os.getenv("ANTHROPIC_API_KEY") or
                os.getenv("ZHIPU_API_KEY") or
                os.getenv("OPENROUTER_API_KEY"))

    def _get_default_api_base(self, provider: str) -> str:
        """获取默认 API Base"""
        defaults = {
            "openai": "https://api.openai.com/v1",
            "anthropic": "https://api.anthropic.com",
            "zhipu": "https://open.bigmodel.cn/api/paas/v4",
            "openrouter": "https://openrouter.ai/api/v1",
        }
        return defaults.get(provider.lower(), "https://api.openai.com/v1")

    # ==================== 工具管理 ====================

    def _refresh_tools(self):
        """刷新工具列表（考虑模式和 skill 权限）"""
        tools = create_tools_for_mode(
            mode_manager=self.mode_manager,
            session_id=self.session_id,
            model_provider=self.model_provider,
            api_key=self.api_key,
            api_base=self.api_base,
            model_name=self.model_name,
            subtask_event_callback=self._subtask_event_callback,
            ws_manager=self._ws_manager
        )
        self._tools = self.skill_manager.filter_tools(tools)

    def set_subtask_callback(self, callback):
        """设置子任务事件回调

        Args:
            callback: 异步回调函数，接收子任务事件字典
        """
        self._subtask_event_callback = callback
        self._refresh_tools()
        if self._agent:
            self._agent.set_tools(self._tools)

    def refresh_tools(self):
        """刷新工具列表（模式切换后调用）"""
        self._refresh_tools()
        if self._agent:
            self._agent.set_tools(self._tools)

    # ==================== CoreAgent 初始化 ====================

    def _build_system_prompt(self) -> str:
        """构建完整系统提示词（包含模式、skill 列表和激活的 skill 提示词）"""
        full_prompt = self.system_prompt

        mode_suffix = self.mode_manager.get_mode_prompt_suffix()
        if mode_suffix:
            full_prompt = f"{full_prompt}\n\n{mode_suffix}"

        skills_list_prompt = self.skill_manager.get_skills_prompt()
        if skills_list_prompt:
            full_prompt = f"{full_prompt}\n\n{skills_list_prompt}"

        active_skill_suffix = self.skill_manager.get_prompt_suffix()
        if active_skill_suffix:
            full_prompt = f"{full_prompt}\n\n{active_skill_suffix}"

        return full_prompt

    def _init_agent(self, force_reinit: bool = False):
        """初始化 CoreAgent

        Args:
            force_reinit: 强制重新初始化（用于更新配置）
        """
        if self._agent is not None and not force_reinit:
            return

        llm_config = LLMConfig(
            provider=self.provider,
            model=self.model_name,
            api_key=self.api_key or "",
            api_base=self.api_base,
            temperature=0.7,
            max_tokens=8192,
            timeout=120,
            top_p=0.9,
        )

        loop_config = AgentLoopConfig(
            system_prompt=self._build_system_prompt(),
            max_iterations=self.max_iterations,
        )

        stream_fn = get_default_stream_fn(llm_config)

        agent = CoreAgent(
            llm_config=llm_config,
            loop_config=loop_config,
            stream_fn=stream_fn,
        )

        agent.set_tools(self._tools)
        self._agent = agent

    # ==================== 模式 / Skill 管理 ====================

    def switch_mode(self, mode: AgentMode) -> bool:
        """切换模式

        Args:
            mode: 目标模式

        Returns:
            是否切换成功
        """
        if self.mode_manager.switch_mode(mode):
            self.refresh_tools()
            self._agent = None
            return True
        return False

    def activate_skill(self, skill_name: str) -> bool:
        """激活指定的 skill

        Args:
            skill_name: Skill 名称

        Returns:
            是否成功激活
        """
        skill = self.skill_manager.get_skill(skill_name)
        if skill:
            self.skill_manager.activate_skill(skill)
            self._refresh_tools()
            self._agent = None
            return True
        return False

    def deactivate_skill(self):
        """停用当前 skill"""
        self.skill_manager.deactivate_skill()
        self._refresh_tools()
        self._agent = None

    def get_current_skill(self):
        """获取当前激活的 skill"""
        return self.skill_manager.current_skill

    def list_skills(self):
        """列出所有可用的 skills"""
        return self.skill_manager.list_skills()

    def get_current_mode(self) -> AgentMode:
        """获取当前模式"""
        return self.mode_manager.get_current_mode()

    def get_available_tools(self) -> List[str]:
        """获取当前可用的工具列表"""
        return [t.name for t in self._tools]

    def get_mode_info(self) -> Dict[str, Any]:
        """获取模式信息"""
        return self.mode_manager.get_mode_info()

    # ==================== 媒体上下文 ====================

    def _get_media_output_dir(self) -> str:
        """获取当前会话的媒体输出目录"""
        base_dir = os.getenv("MEDIA_OUTPUT_DIR", "~/.lumos/media")
        session_id = self.session_id or "default"
        media_dir = os.path.expanduser(f"{base_dir}/{session_id}")
        os.makedirs(media_dir, exist_ok=True)
        return media_dir

    def _build_media_context(self) -> str:
        """构建媒体输出上下文信息"""
        media_dir = self._get_media_output_dir()
        return (
            f"\n<system_reminder>\n"
            f"多媒体输出目录: {media_dir}\n"
            f"【重要】只有以下类型的多媒体文件才应保存到此目录：\n"
            f"  - 图片文件: .png, .jpg, .jpeg, .gif, .webp, .svg\n"
            f"  - 音频文件: .mp3, .wav, .ogg, .m4a\n"
            f"  - 视频文件: .mp4, .webm, .avi\n"
            f"  - 生成的图表/可视化文件\n"
            f"保存多媒体文件后，使用 MEDIA:<路径> 标记返回。\n"
            f"\n"
            f"【注意】代码文件(.py/.js/.ts等)、文本文件(.txt/.md/.json等)、\n"
            f"脚本文件等应保存到用户的工作目录或用户指定的位置，\n"
            f"而不是媒体目录。\n"
            f"</system_reminder>\n"
        )

    # ==================== 调用方法 ====================

    async def invoke(self, query: str, conversation_id: str = "default") -> Dict[str, Any]:
        """调用 Agent（带重试机制）

        Args:
            query: 用户查询
            conversation_id: 会话 ID

        Returns:
            执行结果
        """
        self._init_agent()

        max_retries = 5
        base_delay = 1.0
        max_delay = 60.0
        last_exception = None

        for attempt in range(max_retries):
            try:
                collected_text: list[str] = []

                def on_event(event: CoreAgentEvent) -> None:
                    if event.type == AgentEventType.MESSAGE_DELTA:
                        data = event.data
                        if isinstance(data, dict) and data.get("type") == "text":
                            collected_text.append(data.get("text", ""))

                assert self._agent is not None
                unsub = self._agent.subscribe(on_event)
                try:
                    await self._agent.prompt(query)
                finally:
                    unsub()

                result = "".join(collected_text)
                return {"output": result, "result_type": "success"}
            except Exception as e:
                last_exception = e
                error_str = str(e)

                is_retryable = self._is_retryable_error(error_str)

                if is_retryable and attempt < max_retries - 1:
                    delay = min(base_delay * (2 ** attempt), max_delay)
                    jitter = 0.5 + random.random()
                    actual_delay = delay * jitter

                    error_type, error_desc = self._classify_error(error_str)
                    print(f"[Agent] {error_type}：{error_desc}，{actual_delay:.1f}秒后重试 (第{attempt + 1}/{max_retries}次)...")

                    await asyncio.sleep(actual_delay)
                    continue

                break

        return {
            "output": f"Agent 执行错误: {str(last_exception)}",
            "result_type": "error"
        }

    async def stream(
        self,
        query: str,
        conversation_id: str = "default"
    ) -> AsyncIterator[AgentEvent]:
        """流式调用 Agent（带重试机制）

        Args:
            query: 用户查询
            conversation_id: 会话 ID

        Yields:
            AgentEvent: Agent 事件
        """
        self._init_agent()
        self.reset_loop_detection()

        media_context = self._build_media_context()
        enhanced_query = f"{media_context}{query}"

        max_retries = 5
        base_delay = 1.0
        max_delay = 60.0

        for attempt in range(max_retries):
            has_content = False
            has_error = False
            should_retry = False
            last_event = None

            try:
                # 用 asyncio.Queue 桥接 CoreAgent 的同步事件回调和异步迭代
                event_queue: asyncio.Queue[Optional[AgentEvent]] = asyncio.Queue()

                def on_core_event(core_event: CoreAgentEvent) -> None:
                    agent_event = self._convert_event(core_event)
                    if agent_event:
                        event_queue.put_nowait(agent_event)

                assert self._agent is not None
                unsub = self._agent.subscribe(on_core_event)

                # 启动 prompt 任务
                async def _run_prompt() -> None:
                    try:
                        assert self._agent is not None
                        await self._agent.prompt(enhanced_query)
                    finally:
                        # 发送 sentinel 表示结束
                        event_queue.put_nowait(None)

                prompt_task = asyncio.create_task(_run_prompt())

                try:
                    while True:
                        agent_event = await event_queue.get()
                        if agent_event is None:
                            break
                        last_event = agent_event
                        if agent_event.type == "content_chunk" and agent_event.data:
                            has_content = True
                        elif agent_event.type == "content" and agent_event.data:
                            has_content = True
                        elif agent_event.type == "error":
                            has_error = True
                            if self._is_retryable_error(str(agent_event.data)) and attempt < max_retries - 1:
                                should_retry = True
                                break
                        yield agent_event
                finally:
                    unsub()
                    if not prompt_task.done():
                        prompt_task.cancel()
                        try:
                            await prompt_task
                        except (asyncio.CancelledError, Exception):
                            pass

                if should_retry:
                    delay = min(base_delay * (2 ** attempt), max_delay)
                    jitter = 0.5 + random.random()
                    actual_delay = delay * jitter
                    error_type, error_desc = self._classify_error(
                        str(last_event.data) if last_event else "未知错误"
                    )
                    print(f"[Agent] {error_type}：{error_desc}，{actual_delay:.1f}秒后重试 (第{attempt + 1}/{max_retries}次)...")
                    await asyncio.sleep(actual_delay)
                    continue

                if not has_content and not has_error:
                    yield AgentEvent(
                        type="error",
                        data="未收到模型响应，请检查 API 配置和网络连接"
                    )
                return

            except Exception as e:
                error_str = str(e)
                if self._is_retryable_error(error_str) and attempt < max_retries - 1:
                    delay = min(base_delay * (2 ** attempt), max_delay)
                    jitter = 0.5 + random.random()
                    actual_delay = delay * jitter
                    error_type, error_desc = self._classify_error(error_str)
                    print(f"[Agent] {error_type}：{error_desc}，{actual_delay:.1f}秒后重试 (第{attempt + 1}/{max_retries}次)...")
                    await asyncio.sleep(actual_delay)
                    continue

                error_msg = self._format_error(e)
                yield AgentEvent(type="error", data=error_msg)
                return

    # ==================== 事件转换 ====================

    def _convert_event(self, event: CoreAgentEvent) -> Optional[AgentEvent]:
        """将 CoreAgentEvent 转换为 LumosAgent 的 AgentEvent"""
        if event.type == AgentEventType.MESSAGE_DELTA:
            data = event.data
            if isinstance(data, dict):
                if data.get("type") == "text":
                    return AgentEvent(type="content_chunk", data=data.get("text", ""))
                elif data.get("type") == "thinking":
                    return AgentEvent(type="thinking", data=data.get("thinking", ""))
        elif event.type == AgentEventType.TOOL_START:
            data = event.data
            if isinstance(data, dict):
                tool_info = {
                    "name": data.get("name", ""),
                    "arguments": data.get("arguments", {}),
                    "tool_call_id": data.get("tool_call_id", ""),
                }
                self._track_tool_call(tool_info)
                return AgentEvent(type="tool_call", data=tool_info)
        elif event.type == AgentEventType.TOOL_END:
            data = event.data
            if isinstance(data, dict):
                tool_result_payload = {
                    "result": data.get("result", ""),
                    "tool_name": data.get("name", ""),
                    "tool_call_id": data.get("tool_call_id", ""),
                }
                if not self._loop_warning_injected:
                    loop_warning = self._detect_write_rm_loop()
                    if loop_warning:
                        tool_result_payload["result"] = (
                            str(tool_result_payload.get("result", ""))
                            + loop_warning
                        )
                        self._loop_warning_injected = True
                return AgentEvent(type="tool_result", data=tool_result_payload)
        elif event.type == AgentEventType.ERROR:
            return AgentEvent(type="error", data=event.data)
        elif event.type == AgentEventType.AGENT_END:
            return None
        return None

    # ==================== 错误处理 ====================

    def _is_retryable_error(self, error_str: str) -> bool:
        """判断错误是否可重试"""
        error_lower = error_str.lower()
        retryable_patterns = [
            "connection", "timeout", "timed out", "connect",
            "reset by peer", "broken pipe", "network", "socket",
            "429", "rate limit", "too many requests", "quota", "throttl",
            "500", "502", "503", "504", "server error",
            "internal error", "service unavailable", "bad gateway",
            "openai api", "async conn", "failed to call model",
        ]
        return any(pattern in error_lower for pattern in retryable_patterns)

    def _classify_error(self, error_str: str) -> tuple[str, str]:
        """分类错误并返回用户友好的错误描述"""
        error_lower = error_str.lower()

        if "429" in error_str or "rate limit" in error_lower or "并发" in error_str or "1302" in error_str:
            return "限流", "API 并发数过高，请稍后重试"
        if "401" in error_str or "403" in error_str or "unauthorized" in error_lower or "forbidden" in error_lower:
            return "认证失败", "API Key 无效或已过期"
        if "model" in error_lower and ("not found" in error_lower or "invalid" in error_lower):
            return "模型错误", "模型名称无效，请检查配置"
        if any(code in error_str for code in ["500", "502", "503", "504"]):
            return "服务器错误", "API 服务暂时不可用"
        if any(kw in error_lower for kw in ["connection", "timeout", "connect"]):
            return "连接错误", "网络连接失败"
        return "API 错误", error_str[:100] if len(error_str) > 100 else error_str

    def _format_error(self, e_or_msg) -> str:
        """格式化错误信息"""
        if isinstance(e_or_msg, Exception):
            error_str = str(e_or_msg)
            error_type = type(e_or_msg).__name__
            if hasattr(e_or_msg, 'message'):
                error_str = getattr(e_or_msg, 'message')
            elif hasattr(e_or_msg, 'args') and e_or_msg.args:
                error_str = str(e_or_msg.args[0])
        else:
            error_str = str(e_or_msg)
            error_type = "Error"

        if "Invalid model provider" in error_str:
            return f"模型提供商配置错误: {error_str}\n请检查 provider 设置"
        elif "timeout" in error_str.lower():
            return f"API 连接超时: {error_str}\n请检查网络连接"
        elif "API" in error_str and "error" in error_str.lower():
            return f"API 调用失败: {error_str}\n请检查 API Key 和网络"
        elif "socks" in error_str.lower() or "proxy" in error_str.lower():
            return f"代理错误: {error_str}\n请使用 HTTP 代理或直连"
        elif "api_key" in error_str.lower() or "authentication" in error_str.lower():
            return f"认证失败: {error_str}\n请检查 API Key"
        else:
            return f"{error_type}: {error_str}"

    # ==================== 循环检测 ====================

    def _detect_write_rm_loop(self) -> Optional[str]:
        """检测 write-rm 循环模式"""
        if len(self._tool_call_history) < 4:
            return None

        recent_calls = self._tool_call_history[-10:]
        write_rm_count = 0
        written_files = set()

        for call in recent_calls:
            tool_name = call.get("tool_name", "") or call.get("name", "")
            args = call.get("arguments", {})

            if tool_name == "write_file":
                file_path = args.get("file_path", "")
                if file_path:
                    written_files.add(file_path)
            elif tool_name == "bash":
                command = args.get("command", "")
                if "rm " in command or "rm\n" in command:
                    for written_file in written_files:
                        if written_file in command:
                            write_rm_count += 1

        if write_rm_count >= 2:
            return (
                "\n\n<system_reminder>\n"
                "⚠️ 检测到 write_file → rm 循环模式！\n\n"
                "这通常表示写入的文件有问题。请不要继续删除重试。\n\n"
                "正确做法：\n"
                "1. 使用 read_file 检查写入的文件内容是否正确\n"
                "2. 如果是 Python 脚本，用 bash 执行查看错误信息\n"
                "3. 根据错误信息修复代码（使用 edit_file）\n"
                "4. 如果写入只有 1 行但应该有多行，可能是换行符格式问题\n\n"
                "停止删除文件，改为诊断和修复问题。\n"
                "</system_reminder>\n"
            )
        return None

    def _track_tool_call(self, tool_info: Dict[str, Any]):
        """记录工具调用"""
        self._tool_call_history.append({
            "tool_name": tool_info.get("name", ""),
            "arguments": tool_info.get("arguments", {}),
        })
        if len(self._tool_call_history) > 50:
            self._tool_call_history = self._tool_call_history[-30:]

    def reset_loop_detection(self):
        """重置循环检测状态（新对话时调用）"""
        self._tool_call_history = []
        self._loop_warning_injected = False


# ==================== 工厂函数 ====================

def create_lumos_agent(
    provider: str = "openai",
    api_key: Optional[str] = None,
    model: Optional[str] = None,
    api_base: Optional[str] = None,
    **kwargs
) -> LumosAgent:
    """创建 Lumos Agent

    Args:
        provider: 模型提供商 (openai, anthropic, zhipu)
        api_key: API 密钥（可从环境变量获取）
        model: 模型名称
        api_base: API Base URL
        **kwargs: 其他参数

    Returns:
        LumosAgent 实例
    """
    default_models = {
        "openai": "gpt-4o",
        "anthropic": "claude-sonnet-4-5-20250929",
        "zhipu": "glm-4",
        "openrouter": "zhipu/glm-4-plus",
    }

    model_name = model or default_models.get(provider.lower(), "gpt-4o")

    return LumosAgent(
        model_provider=provider,
        api_key=api_key,
        api_base=api_base,
        model_name=model_name,
        **kwargs
    )


def create_agent_from_env() -> LumosAgent:
    """从环境变量创建 Agent

    支持的环境变量：
    - OPENAI_API_KEY / ANTHROPIC_API_KEY / ZHIPU_API_KEY
    - MODEL_PROVIDER (默认 openai)
    - MODEL_NAME
    - API_BASE_URL

    Returns:
        LumosAgent 实例
    """
    if os.getenv("ZHIPU_API_KEY"):
        provider = "zhipu"
        api_key = os.getenv("ZHIPU_API_KEY")
    elif os.getenv("OPENROUTER_API_KEY"):
        provider = "openrouter"
        api_key = os.getenv("OPENROUTER_API_KEY")
    elif os.getenv("ANTHROPIC_API_KEY"):
        provider = "anthropic"
        api_key = os.getenv("ANTHROPIC_API_KEY")
    elif os.getenv("OPENAI_API_KEY"):
        provider = "openai"
        api_key = os.getenv("OPENAI_API_KEY")
    else:
        provider = os.getenv("MODEL_PROVIDER", "openai")
        api_key = None

    provider = os.getenv("MODEL_PROVIDER", provider)
    model = os.getenv("MODEL_NAME")
    api_base = os.getenv("API_BASE_URL")

    return create_lumos_agent(
        provider=provider,
        api_key=api_key,
        model=model,
        api_base=api_base
    )
