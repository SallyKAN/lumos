"""
Agent 服务层

封装 LumosAgent，提供 Web API 友好的接口。
"""

import asyncio
from dataclasses import dataclass, field
from datetime import datetime
import logging
import os
from typing import Any, AsyncIterator, Dict, List, Optional

from ..websocket.manager import WebSocketManager, get_websocket_manager
from ..websocket.protocol import (
    create_todo_update_message,
    create_interrupt_result_message,
    create_skill_update_message,
    create_skill_install_progress_message,
    create_skill_install_result_message,
    create_subtask_update_message,
    InterruptResultPayload,
    SkillInstallStage,
)

# 导入核心模块
from ...agents.lumos_agent import (
    AgentEvent,
    LumosAgent,
    create_lumos_agent,
)
from ...agents.mode_manager import AgentMode, AgentModeManager
from ...session.session_manager import SessionManager
from ...tools.todo_tools import TodoPersistenceManager
from ...intent.intent_classifier import IntentClassifier, InterruptIntent
from ...interrupt.interrupt_handler import TaskInterruptHandler
from ...media.media_parser import parse_media_content


logger = logging.getLogger(__name__)


@dataclass
class TodoSnapshot:
    """任务列表快照"""
    task_description: str           # 任务描述（用于匹配）
    todos: List[Dict[str, Any]]     # 任务列表
    timestamp: str                  # 保存时间


@dataclass
class AgentSession:
    """Agent 会话封装"""
    session_id: str
    agent: LumosAgent
    mode_manager: AgentModeManager
    todo_manager: TodoPersistenceManager
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    last_activity: str = field(default_factory=lambda: datetime.now().isoformat())
    is_processing: bool = False
    current_task: Optional[str] = None
    # 中断控制
    _cancel_event: asyncio.Event = field(default_factory=asyncio.Event)
    _current_process_task: Optional[asyncio.Task] = field(
        default=None, repr=False
    )
    # 任务列表快照存储: task_key -> TodoSnapshot
    _todo_snapshots: Dict[str, TodoSnapshot] = field(default_factory=dict)

    def update_activity(self):
        """更新最后活动时间"""
        self.last_activity = datetime.now().isoformat()

    def request_cancel(self):
        """请求取消当前任务"""
        self._cancel_event.set()

    def reset_cancel(self):
        """重置取消状态"""
        self._cancel_event.clear()

    def is_cancelled(self) -> bool:
        """检查是否已请求取消"""
        return self._cancel_event.is_set()

    def save_todo_snapshot(self, task_description: str, todos: List[Any]):
        """保存任务列表快照

        Args:
            task_description: 任务描述
            todos: 任务列表
        """
        if not task_description or not todos:
            return

        # 使用任务描述的前 50 个字符作为 key
        task_key = self._get_task_key(task_description)
        todos_data = [
            t.to_dict() if hasattr(t, 'to_dict') else t for t in todos
        ]

        self._todo_snapshots[task_key] = TodoSnapshot(
            task_description=task_description,
            todos=todos_data,
            timestamp=datetime.now().isoformat()
        )
        logger.info(
            f"Saved todo snapshot for task: {task_key} "
            f"({len(todos_data)} items)"
        )

    def find_todo_snapshot(self, user_input: str) -> Optional[TodoSnapshot]:
        """查找匹配的任务列表快照

        Args:
            user_input: 用户输入

        Returns:
            匹配的快照或 None
        """
        if not self._todo_snapshots:
            return None

        user_input_lower = user_input.lower()

        # 尝试精确匹配 key
        for task_key, snapshot in self._todo_snapshots.items():
            # 检查用户输入是否包含任务关键词
            task_words = set(task_key.lower().split())
            # 过滤停用词
            stop_words = {
                "帮我", "帮", "我", "请", "查", "继续", "恢复",
                "的", "了", "吧", "把", "下"
            }
            task_words -= stop_words

            if task_words:
                # 如果任务关键词中有任意一个出现在用户输入中
                matched = sum(
                    1 for w in task_words if w in user_input_lower
                )
                if matched >= 1 and matched >= len(task_words) * 0.5:
                    logger.info(f"Found matching snapshot: {task_key}")
                    return snapshot

        return None

    def restore_todo_snapshot(
        self,
        snapshot: TodoSnapshot
    ) -> List[Dict[str, Any]]:
        """恢复任务列表快照

        Args:
            snapshot: 快照

        Returns:
            恢复的任务列表
        """
        return snapshot.todos

    def _get_task_key(self, task_description: str) -> str:
        """获取任务的 key（前 50 个字符）"""
        return task_description[:50].strip()


class AgentService:
    """Agent 服务

    管理 Agent 会话，处理消息，广播事件。
    """

    def __init__(self):
        # session_id -> AgentSession
        self._sessions: Dict[str, AgentSession] = {}
        # 会话管理器（持久化）
        self._session_manager = SessionManager()
        # WebSocket 管理器
        self._ws_manager: Optional[WebSocketManager] = None
        # 意图分类器
        self._intent_classifier = IntentClassifier()
        # 锁
        self._lock = asyncio.Lock()

    @property
    def ws_manager(self) -> WebSocketManager:
        """获取 WebSocket 管理器"""
        if self._ws_manager is None:
            self._ws_manager = get_websocket_manager()
        return self._ws_manager

    def _get_api_base_url(self) -> str:
        """获取 API 基础 URL。

        用于生成媒体文件的访问 URL。

        Returns:
            API 基础 URL
        """
        host = os.getenv("HOST", "127.0.0.1")
        port = os.getenv("PORT", "8000")
        return f"http://{host}:{port}"

    async def get_or_create_session(
        self,
        session_id: Optional[str] = None,
        provider: str = "openai",
        api_key: Optional[str] = None,
        api_base: Optional[str] = None,
        model: Optional[str] = None,
        project_path: Optional[str] = None
    ) -> AgentSession:
        """获取或创建 Agent 会话

        Args:
            session_id: 会话 ID（可选，不提供则创建新会话）
            provider: 模型提供商
            api_key: API 密钥
            api_base: API Base URL
            model: 模型名称
            project_path: 项目路径

        Returns:
            AgentSession 对象
        """
        async with self._lock:
            # 如果已存在内存中的会话，直接返回
            if session_id and session_id in self._sessions:
                session = self._sessions[session_id]
                session.update_activity()
                return session

            # 创建新会话或恢复已有会话
            if session_id and self._session_manager.session_exists(session_id):
                # 恢复已有会话
                return await self._restore_session(
                    session_id, provider, api_key, api_base, model
                )
            else:
                # 创建新会话
                return await self._create_new_session(
                    provider, api_key, api_base, model, project_path
                )

    def _load_config_file(self) -> Dict[str, Any]:
        """加载配置文件 ~/.lumos/config.yaml"""
        config_path = os.path.expanduser("~/.lumos/config.yaml")
        if os.path.exists(config_path):
            try:
                import yaml
                with open(config_path, 'r') as f:
                    return yaml.safe_load(f) or {}
            except Exception as e:
                logger.warning(f"Failed to load config file: {e}")
        return {}

    def _get_api_key_from_env(self, provider: str) -> Optional[str]:
        """从环境变量获取 API Key

        Args:
            provider: 模型提供商

        Returns:
            API Key 或 None
        """
        key_mapping = {
            "openai": "OPENAI_API_KEY",
            "anthropic": "ANTHROPIC_API_KEY",
            "zhipu": "ZHIPU_API_KEY",
            "openrouter": "OPENROUTER_API_KEY",
        }
        env_key = key_mapping.get(provider.lower())
        if env_key:
            return os.getenv(env_key)
        return None

    def _get_config(self) -> tuple:
        """获取配置（优先级：环境变量 > 配置文件）

        Returns:
            (provider, api_key, api_base, model)
        """
        # 先从配置文件读取
        config = self._load_config_file()
        provider = config.get("provider", "openai")
        api_key = config.get("api_key")
        api_base = config.get("api_base_url")
        model = config.get("model")

        # 环境变量覆盖
        env_presence = {}
        for p, env_var in [
            ("zhipu", "ZHIPU_API_KEY"),
            ("openrouter", "OPENROUTER_API_KEY"),
            ("anthropic", "ANTHROPIC_API_KEY"),
            ("openai", "OPENAI_API_KEY"),
        ]:
            key = os.getenv(env_var)
            env_presence[env_var] = bool(key)
            if key:
                provider = p
                api_key = key
                break

        # MODEL_NAME 和 API_BASE_URL 环境变量覆盖
        env_model = os.getenv("MODEL_NAME")
        if env_model:
            model = env_model
        env_api_base = os.getenv("API_BASE_URL")
        if env_api_base:
            api_base = env_api_base

        return provider, api_key, api_base, model

    async def _create_new_session(
        self,
        provider: str,
        api_key: Optional[str],
        api_base: Optional[str],
        model: Optional[str],
        project_path: Optional[str]
    ) -> AgentSession:
        """创建新会话"""
        # 使用 SessionManager 创建会话
        project_path = project_path or os.getcwd()
        session_id = self._session_manager.create_session(project_path)

        # 如果没有提供 API Key，从配置文件和环境变量读取
        if not api_key:
            cfg_provider, cfg_api_key, cfg_api_base, cfg_model = self._get_config()
            if cfg_api_key:
                provider = cfg_provider
                api_key = cfg_api_key
                api_base = api_base or cfg_api_base
                model = model or cfg_model
                logger.info(f"Using config: provider={provider}")

        # 创建模式管理器
        mode_manager = AgentModeManager()

        # 创建 Agent（传入 ws_manager 用于 ask_user_question 工具）
        agent = create_lumos_agent(
            provider=provider,
            api_key=api_key,
            model=model,
            api_base=api_base,
            mode_manager=mode_manager,
            session_id=session_id,
            project_root=project_path,
            ws_manager=self.ws_manager
        )

        # 设置子任务事件回调
        async def subtask_callback(event_data: dict):
            await self._broadcast_subtask_event(session_id, event_data)
        agent.set_subtask_callback(subtask_callback)

        # 创建 Todo 管理器
        todo_manager = TodoPersistenceManager(session_id)

        # 创建会话对象
        session = AgentSession(
            session_id=session_id,
            agent=agent,
            mode_manager=mode_manager,
            todo_manager=todo_manager
        )

        self._sessions[session_id] = session
        logger.info(f"Created new agent session: {session_id}")

        return session

    async def _restore_session(
        self,
        session_id: str,
        provider: str,
        api_key: Optional[str],
        api_base: Optional[str],
        model: Optional[str]
    ) -> AgentSession:
        """恢复已有会话"""
        # 加载会话数据
        metadata, _, _ = self._session_manager.load_session(session_id)

        if not metadata:
            raise ValueError(f"Session {session_id} not found")

        # 如果没有提供 API Key，从配置文件和环境变量读取
        if not api_key:
            cfg_provider, cfg_api_key, cfg_api_base, cfg_model = self._get_config()
            if cfg_api_key:
                provider = cfg_provider
                api_key = cfg_api_key
                api_base = api_base or cfg_api_base
                model = model or cfg_model

        # 创建模式管理器并恢复模式
        mode_manager = AgentModeManager()
        if metadata.mode:
            try:
                mode_manager.switch_mode(AgentMode(metadata.mode))
            except ValueError:
                pass

        # 创建 Agent（传入 ws_manager 用于 ask_user_question 工具）
        agent = create_lumos_agent(
            provider=provider,
            api_key=api_key,
            model=model,
            api_base=api_base,
            mode_manager=mode_manager,
            session_id=session_id,
            project_root=metadata.project_path,
            ws_manager=self.ws_manager
        )

        # 设置子任务事件回调
        async def subtask_callback(event_data: dict):
            await self._broadcast_subtask_event(session_id, event_data)
        agent.set_subtask_callback(subtask_callback)

        # 创建 Todo 管理器
        todo_manager = TodoPersistenceManager(session_id)

        # 创建会话对象
        session = AgentSession(
            session_id=session_id,
            agent=agent,
            mode_manager=mode_manager,
            todo_manager=todo_manager
        )

        self._sessions[session_id] = session

        # 更新会话状态
        self._session_manager.update_status(session_id, "active")

        # 加载并注入历史消息到 SDK 的 ContextEngine
        messages = self._session_manager.load_messages(session_id)
        if messages:
            self._inject_history_to_agent(agent, session_id, messages)

        logger.info(f"Restored agent session: {session_id}")
        return session

    def _inject_history_to_agent(
        self,
        agent,
        session_id: str,
        messages: List[Dict[str, Any]]
    ):
        """将持久化的消息历史注入到 SDK 的 ContextEngine

        Args:
            agent: LumosAgent 实例
            session_id: 会话 ID
            messages: 消息列表 [{"role": "user/assistant", "content": "..."}]
        """
        try:
            from lumos.core.utils.llm.messages import (
                HumanMessage, AIMessage
            )

            # 确保 Agent 已初始化（会创建 context_engine）
            agent._init_agent()

            # 获取 context_engine 和 agent_context
            context_engine = agent._agent.context_engine
            agent_context = context_engine.get_agent_context(session_id)

            # 转换消息格式
            sdk_messages = []
            for msg in messages:
                role = msg.get("role")
                content = msg.get("content", "")
                if role == "user":
                    sdk_messages.append(HumanMessage(content=content))
                elif role == "assistant":
                    sdk_messages.append(AIMessage(content=content))

            # 批量注入
            if sdk_messages:
                agent_context.batch_add_messages(sdk_messages)
                logger.info(
                    f"Injected {len(sdk_messages)} messages to session "
                    f"{session_id}"
                )
        except Exception as e:
            logger.warning(f"Failed to inject history to agent: {e}")

    async def process_message(
        self,
        session_id: str,
        message: str,
        conversation_id: str = "default"
    ) -> AsyncIterator[AgentEvent]:
        """处理用户消息

        Args:
            session_id: 会话 ID
            message: 用户消息
            conversation_id: 对话 ID

        Yields:
            AgentEvent: Agent 事件
        """
        session = self._sessions.get(session_id)
        if not session:
            yield AgentEvent(type="error", data="Session not found")
            return

        # 重置取消状态
        session.reset_cancel()

        # 设置处理状态
        session.is_processing = True
        session.current_task = message[:50] + "..." if len(message) > 50 else message
        session.update_activity()

        # 通知 WebSocket 客户端
        await self.ws_manager.set_processing_status(
            session_id, True, session.current_task
        )

        # 保存用户消息到持久化存储
        self._session_manager.append_message(session_id, {
            "role": "user",
            "content": message,
            "timestamp": datetime.now().isoformat()
        })

        # 检查是否是显式 skill 命令（快速路径）
        skill_result = await self._handle_skill_command(session, message)
        if skill_result:
            # 显式 skill 命令已处理，将 skill 内容注入到消息中
            message = skill_result

        # 收集助手回复
        full_response = ""

        try:
            # 流式处理消息
            async for event in session.agent.stream(message, conversation_id):
                # 检查是否已请求取消
                if session.is_cancelled():
                    logger.info(
                        f"Task cancelled for session {session_id}"
                    )
                    yield AgentEvent(type="content", data="[任务已中断]")
                    break

                # 收集助手回复内容
                if event.type == "content_chunk" and event.data:
                    full_response += event.data
                elif event.type == "content" and event.data:
                    # 完整内容事件（非流式）
                    if not full_response:
                        full_response = event.data

                # 广播事件到 WebSocket
                await self.ws_manager.broadcast_agent_event(
                    session_id, event.type, event.data
                )

                # 如果是 Todo 相关的工具调用，广播 Todo 更新
                if event.type == "tool_result":
                    await self._check_and_broadcast_todos(session_id)

                yield event

            # 只有在未取消且有回复时才保存助手消息
            if not session.is_cancelled() and full_response:
                # 解析 MEDIA 标记
                clean_content, media_items = parse_media_content(
                    full_response,
                    api_base_url=self._get_api_base_url()
                )

                # 如果有媒体项，广播媒体内容事件
                if media_items:
                    await self.ws_manager.broadcast_agent_event(
                        session_id,
                        "media_content",
                        {
                            "content": clean_content,
                            "media_items": media_items
                        }
                    )
                    logger.info(
                        f"Broadcast {len(media_items)} media items "
                        f"for session {session_id}"
                    )

                self._session_manager.append_message(session_id, {
                    "role": "assistant",
                    "content": full_response,
                    "timestamp": datetime.now().isoformat()
                })
                self._session_manager.increment_message_count(session_id)

        except asyncio.CancelledError:
            logger.info(f"Task cancelled for session {session_id}")
            yield AgentEvent(type="content", data="[任务已中断]")

        except Exception as e:
            logger.error(f"Error processing message: {e}")
            error_event = AgentEvent(type="error", data=str(e))
            await self.ws_manager.broadcast_agent_event(
                session_id, "error", str(e)
            )
            yield error_event

        finally:
            # 重置处理状态
            session.is_processing = False
            session.current_task = None
            await self.ws_manager.set_processing_status(session_id, False)

    async def _check_and_broadcast_todos(self, session_id: str):
        """检查并广播 Todo 更新"""
        session = self._sessions.get(session_id)
        if not session:
            return

        todos = session.todo_manager.load_todos()
        if todos:
            todos_data = [todo.to_dict() for todo in todos]
            await self.ws_manager.broadcast_to_session(
                session_id,
                create_todo_update_message(todos_data, session_id)
            )

    async def _handle_skill_command(
        self,
        session: AgentSession,
        message: str
    ) -> Optional[str]:
        """处理显式 skill 命令

        支持格式:
        - /skill <skill-name> [args]
        - /<skill-name> [args]

        Args:
            session: Agent 会话
            message: 用户消息

        Returns:
            如果是 skill 命令，返回增强后的消息；否则返回 None
        """
        import re

        message = message.strip()

        # 匹配 /skill <name> [args]
        skill_cmd_pattern = r'^/skill\s+(\S+)(?:\s+(.*))?$'
        match = re.match(skill_cmd_pattern, message, re.IGNORECASE)

        skill_name = None
        args = ""

        if match:
            skill_name = match.group(1)
            args = match.group(2) or ""
        elif message.startswith('/'):
            # 匹配 /<skill-name> [args]
            parts = message[1:].split(maxsplit=1)
            if parts:
                potential_skill_name = parts[0]
                # 检查是否是已知的 skill
                skill = session.agent.skill_manager.get_skill(
                    potential_skill_name
                )
                if skill:
                    skill_name = potential_skill_name
                    args = parts[1] if len(parts) > 1 else ""

        if not skill_name:
            return None

        # 获取并激活 skill
        skill = session.agent.skill_manager.get_skill(skill_name)
        if not skill:
            return None

        # 激活 skill
        session.agent.skill_manager.activate_skill(skill)

        # 刷新工具列表以应用 skill 的工具限制
        session.agent.refresh_tools()

        # 重新初始化 agent 以应用新的提示词
        session.agent._agent = None

        # 构建增强后的消息
        enhanced_message = f"""[系统通知] 已激活 Skill: {skill.name}

## Skill 指导

{skill.content}

---

用户请求: {args if args else '请按照上述 Skill 指导完成任务'}"""

        logger.info(f"Activated skill '{skill_name}' for session {session.session_id}")

        return enhanced_message

    async def _broadcast_subtask_event(
        self,
        session_id: str,
        event_data: dict
    ):
        """广播子任务事件到 WebSocket

        Args:
            session_id: 会话 ID
            event_data: 子任务事件数据
        """
        msg = create_subtask_update_message(
            task_id=event_data.get("task_id", ""),
            description=event_data.get("description", ""),
            status=event_data.get("status", ""),
            index=event_data.get("index", 0),
            total=event_data.get("total", 1),
            tool_name=event_data.get("tool_name"),
            tool_count=event_data.get("tool_count", 0),
            message=event_data.get("message"),
            is_parallel=event_data.get("is_parallel", False),
            session_id=session_id
        )
        await self.ws_manager.broadcast_to_session(session_id, msg)

    def _build_resume_context(
        self,
        snapshot: TodoSnapshot,
        user_input: str
    ) -> str:
        """构建恢复上下文消息

        生成一个包含任务列表状态的消息，让 LLM 知道应该从哪里继续执行。

        Args:
            snapshot: 恢复的任务快照
            user_input: 用户原始输入

        Returns:
            包含上下文的消息字符串
        """
        todos = snapshot.todos
        task_desc = snapshot.task_description

        # 分类任务状态
        completed = []
        in_progress = []
        pending = []

        for todo in todos:
            status = todo.get("status", "pending")
            content = todo.get("content", "")
            result = todo.get("result")

            if status == "completed":
                if result:
                    completed.append(f"- {content} → 结果: {result}")
                else:
                    completed.append(f"- {content}")
            elif status == "in_progress":
                in_progress.append(f"- {content}")
            else:
                pending.append(f"- {content}")

        # 构建上下文消息
        context_parts = [
            f"用户请求恢复之前的任务: {task_desc}",
            "",
            "【已恢复的任务列表】"
        ]

        if completed:
            context_parts.append("✅ 已完成:")
            context_parts.extend(completed)

        if in_progress:
            context_parts.append("🔄 进行中:")
            context_parts.extend(in_progress)

        if pending:
            context_parts.append("⏳ 待处理:")
            context_parts.extend(pending)

        context_parts.extend([
            "",
            "请注意：任务列表已恢复，不要重新创建任务列表。",
            "请从上次中断的位置继续执行剩余任务。",
            f"如果有进行中的任务，请继续执行；否则执行下一个待处理任务。"
        ])

        return "\n".join(context_parts)

    async def handle_interrupt(
        self,
        session_id: str,
        new_input: Optional[str] = None,
        explicit_intent: Optional[str] = None
    ) -> Dict[str, Any]:
        """处理中断请求

        使用 IntentClassifier 自动识别用户意图，或使用显式指定的意图。

        Args:
            session_id: 会话 ID
            new_input: 用户新输入（可选）
            explicit_intent: 显式指定的意图（如 "pause"），优先于自动识别

        Returns:
            处理结果，包含 intent, success, message 等字段
        """
        session = self._sessions.get(session_id)
        if not session:
            return {
                "intent": "cancel",
                "success": False,
                "message": "会话不存在",
                "new_input": None,
                "merged_input": None,
                "paused_task": None
            }

        current_task = session.current_task or "未知任务"
        paused_task = None

        # 确定意图：显式指定 > 自动识别
        if explicit_intent:
            intent_str = explicit_intent
        elif new_input:
            # 获取对话历史，用于意图识别上下文
            conversation_history = self.get_conversation_history(session_id)

            # 使用意图分类器识别
            intent_result = await self._intent_classifier.classify(
                current_task,
                new_input,
                use_llm=False,  # 先使用规则匹配，快速响应
                conversation_history=conversation_history
            )
            intent_str = intent_result.intent.value
            logger.info(
                f"Intent classified: {intent_str} "
                f"(confidence: {intent_result.confidence}, "
                f"reason: {intent_result.reason})"
            )
        else:
            # 无输入且无显式意图，默认取消
            intent_str = "cancel"

        # 根据意图执行操作
        result = {
            "intent": intent_str,
            "success": True,
            "message": "",
            "new_input": None,
            "merged_input": None,
            "paused_task": None
        }

        if intent_str == "switch":
            # 切换任务：保存当前任务的 Todo 快照，然后停止
            todos = session.todo_manager.load_todos()
            if todos and current_task:
                session.save_todo_snapshot(current_task, todos)

            session.request_cancel()  # 请求取消当前任务
            session.is_processing = False
            session.current_task = None
            await self.ws_manager.set_processing_status(session_id, False)
            result["message"] = "已切换到新任务"
            result["new_input"] = new_input

        elif intent_str == "pause":
            # 暂停任务：保存 Todo 快照和状态
            paused_task = current_task
            todos = session.todo_manager.load_todos()
            if todos and current_task:
                session.save_todo_snapshot(current_task, todos)

            session.request_cancel()  # 请求取消当前任务
            session.is_processing = False
            session.current_task = None
            await self.ws_manager.set_processing_status(session_id, False)
            self._session_manager.update_status(session_id, "paused")
            result["message"] = "任务已暂停，可随时恢复"
            result["paused_task"] = paused_task

        elif intent_str == "cancel":
            # 取消任务（不保存快照）
            session.request_cancel()  # 请求取消当前任务
            session.is_processing = False
            session.current_task = None
            await self.ws_manager.set_processing_status(session_id, False)
            result["message"] = "任务已取消"

        elif intent_str == "supplement":
            # 补充信息：合并到当前任务
            merged = f"{current_task}\n\n补充信息: {new_input}"
            result["message"] = ""  # 补充信息无需提示
            result["merged_input"] = merged
            # 不停止处理，继续执行

        elif intent_str == "resume":
            # 恢复任务：尝试恢复 Todo 快照
            self._session_manager.update_status(session_id, "active")

            # 查找并恢复匹配的 Todo 快照
            if new_input:
                snapshot = session.find_todo_snapshot(new_input)
                if snapshot:
                    # 恢复 Todo 列表
                    from ...tools.todo_tools import TodoItem
                    restored_todos = [
                        TodoItem(**t) for t in snapshot.todos
                    ]
                    session.todo_manager.save_todos(restored_todos)

                    # 广播 Todo 更新
                    await self.ws_manager.broadcast_to_session(
                        session_id,
                        create_todo_update_message(snapshot.todos, session_id)
                    )

                    # 构建恢复上下文消息，让 LLM 知道应该继续执行
                    context_msg = self._build_resume_context(
                        snapshot, new_input
                    )
                    result["merged_input"] = context_msg
                    result["message"] = (
                        f"已恢复任务: {snapshot.task_description[:30]}..."
                    )
                    logger.info(
                        f"Restored todo snapshot: {len(snapshot.todos)} items"
                    )
                else:
                    result["message"] = "任务已恢复（未找到历史任务列表）"
            else:
                result["message"] = "任务已恢复"

        else:
            result["success"] = False
            result["message"] = f"未知意图: {intent_str}"

        return result

    def switch_mode(self, session_id: str, mode: str) -> bool:
        """切换模式

        Args:
            session_id: 会话 ID
            mode: 目标模式 (BUILD/PLAN/REVIEW)

        Returns:
            是否成功（包括已经是目标模式的情况）
        """
        session = self._sessions.get(session_id)
        if not session:
            logger.warning(f"Session not found: {session_id}")
            return False

        try:
            target_mode = AgentMode(mode.lower())

            # 检查是否已经是目标模式
            current_mode = session.mode_manager.get_current_mode()
            if current_mode == target_mode:
                # 已经是目标模式，视为成功
                return True

            success = session.agent.switch_mode(target_mode)

            if success:
                # 更新持久化的模式
                metadata = self._session_manager._load_metadata(session_id)
                if metadata:
                    metadata.mode = mode.upper()
                    self._session_manager._save_metadata(session_id, metadata)

                # 广播模式变更
                asyncio.create_task(
                    self.ws_manager.broadcast_agent_event(
                        session_id, "mode_change", {"mode": mode.upper()}
                    )
                )

            return success
        except ValueError:
            return False

    def get_session_info(self, session_id: str) -> Optional[Dict[str, Any]]:
        """获取会话信息

        Args:
            session_id: 会话 ID

        Returns:
            会话信息字典
        """
        session = self._sessions.get(session_id)
        if not session:
            # 尝试从持久化存储加载
            metadata, _, todos = self._session_manager.load_session(session_id)
            if metadata:
                return {
                    "session_id": session_id,
                    "title": metadata.title,
                    "project_path": metadata.project_path,
                    "mode": metadata.mode,
                    "status": metadata.status,
                    "message_count": metadata.message_count,
                    "created_at": metadata.created_at,
                    "updated_at": metadata.updated_at,
                    "is_active": False,
                    "is_processing": False,
                    "todos": [t.to_dict() for t in todos]
                }
            return None

        # 从内存中的会话获取信息
        metadata = self._session_manager._load_metadata(session_id)
        todos = session.todo_manager.load_todos()

        return {
            "session_id": session_id,
            "title": metadata.title if metadata else f"Session {session_id[:15]}",
            "project_path": metadata.project_path if metadata else "",
            "mode": session.mode_manager.get_current_mode().value,
            "status": "active",
            "message_count": metadata.message_count if metadata else 0,
            "created_at": session.created_at,
            "updated_at": session.last_activity,
            "is_active": True,
            "is_processing": session.is_processing,
            "current_task": session.current_task,
            "tools": session.agent.get_available_tools(),
            "todos": [t.to_dict() for t in todos]
        }

    def list_sessions(
        self,
        project_path: Optional[str] = None,
        limit: int = 20
    ) -> List[Dict[str, Any]]:
        """列出会话

        Args:
            project_path: 按项目路径过滤
            limit: 返回数量限制

        Returns:
            会话信息列表
        """
        sessions = self._session_manager.list_sessions(
            project_path=project_path,
            limit=limit
        )

        result = []
        for metadata in sessions:
            info = {
                "session_id": metadata.session_id,
                "title": metadata.title,
                "project_path": metadata.project_path,
                "mode": metadata.mode,
                "status": metadata.status,
                "message_count": metadata.message_count,
                "created_at": metadata.created_at,
                "updated_at": metadata.updated_at,
                "is_active": metadata.session_id in self._sessions
            }
            result.append(info)

        return result

    async def delete_session(self, session_id: str) -> bool:
        """删除会话

        Args:
            session_id: 会话 ID

        Returns:
            是否成功
        """
        # 从内存中移除
        async with self._lock:
            if session_id in self._sessions:
                del self._sessions[session_id]

        # 从持久化存储删除
        return self._session_manager.delete_session(session_id)

    def get_todos(self, session_id: str) -> List[Dict[str, Any]]:
        """获取 Todo 列表

        Args:
            session_id: 会话 ID

        Returns:
            Todo 列表
        """
        session = self._sessions.get(session_id)
        if session:
            todos = session.todo_manager.load_todos()
        else:
            # 从持久化存储加载
            todo_manager = TodoPersistenceManager(session_id)
            todos = todo_manager.load_todos()

        return [t.to_dict() for t in todos]

    def get_conversation_history(
        self,
        session_id: str,
        conversation_id: Optional[str] = None,
        max_messages: int = 20
    ) -> List[Dict[str, str]]:
        """获取指定会话的对话历史

        从 SDK 的 ContextEngine 中获取对话历史，用于意图识别等场景。

        Args:
            session_id: 会话 ID
            conversation_id: 对话 ID（默认使用 session_id）
            max_messages: 最大返回消息数

        Returns:
            对话历史列表 [{"role": "user/assistant", "content": "..."}]
        """
        session = self._sessions.get(session_id)
        if not session:
            logger.warning(
                f"Session {session_id} not found for get_conversation_history"
            )
            return []

        # 确保 Agent 已初始化
        if not hasattr(session.agent, '_agent') or session.agent._agent is None:
            logger.warning(
                f"Agent not initialized for session {session_id}"
            )
            return []

        conv_id = conversation_id or session_id

        try:
            context_engine = session.agent._agent.context_engine
            agent_context = context_engine.get_agent_context(conv_id)
            messages = agent_context.get_messages()

            # 转换为简单格式
            result = []
            for msg in messages[-max_messages:]:
                result.append({
                    "role": msg.role,
                    "content": str(msg.content)
                })
            return result
        except Exception as e:
            logger.warning(f"Failed to get conversation history: {e}")
            return []

    async def update_todo(
        self,
        session_id: str,
        task_id: str,
        status: str
    ) -> Dict[str, Any]:
        """更新 Todo 状态

        Args:
            session_id: 会话 ID
            task_id: 任务 ID
            status: 新状态

        Returns:
            更新结果
        """
        session = self._sessions.get(session_id)
        if session:
            todo_manager = session.todo_manager
        else:
            todo_manager = TodoPersistenceManager(session_id)

        todos = todo_manager.load_todos()

        # 查找并更新任务
        found = False
        for todo in todos:
            if todo.id.startswith(task_id) or todo.id == task_id:
                todo.status = status
                todo.updatedAt = datetime.now().isoformat()
                found = True
                break

        if not found:
            return {"success": False, "error": f"Task {task_id} not found"}

        # 保存
        if not todo_manager.save_todos(todos):
            return {"success": False, "error": "Failed to save todos"}

        # 广播更新
        todos_data = [t.to_dict() for t in todos]
        from ..websocket.protocol import create_todo_update_message
        await self.ws_manager.broadcast_to_session(
            session_id,
            create_todo_update_message(todos_data, session_id)
        )

        return {"success": True, "todos": todos_data}

    # ========================================================================
    # Skills 管理
    # ========================================================================

    async def handle_skill_action(
        self,
        session_id: str,
        action: str,
        spec: Optional[str] = None,
        force: bool = False
    ) -> Dict[str, Any]:
        """处理 Skill 操作

        Args:
            session_id: 会话 ID
            action: 操作类型 (list, list_installed, install, uninstall)
            spec: 插件规格 (安装/卸载时需要)
            force: 是否强制重装 (仅安装时有效)

        Returns:
            操作结果
        """
        from ...skills import SkillManager

        # 获取或创建 SkillManager
        manager = SkillManager()
        manager.load_skills()

        if action == "list":
            # 列出所有 skills
            skills = manager.list_skills()
            skills_data = [
                {
                    "name": s.name,
                    "description": s.description,
                    "source": s.source.value,
                    "version": s.metadata.version,
                    "author": s.metadata.author,
                    "tags": s.metadata.tags,
                    "allowed_tools": list(s.allowed_tools)
                }
                for s in skills
            ]

            # 广播 skill 列表
            msg = create_skill_update_message(skills_data, session_id)
            await self.ws_manager.broadcast_to_session(session_id, msg)

            return {"success": True, "skills": skills_data}

        elif action == "list_installed":
            # 列出已安装插件
            plugins = manager.list_installed_plugins()
            plugins_data = [
                {
                    "plugin_name": p.plugin_name,
                    "marketplace": p.marketplace,
                    "spec": p.spec,
                    "version": p.version,
                    "installed_at": p.installed_at.isoformat(),
                    "git_commit": p.git_commit,
                    "skills": p.skills
                }
                for p in plugins
            ]

            return {"success": True, "plugins": plugins_data}

        elif action == "install":
            if not spec:
                return {"success": False, "error": "spec 参数不能为空"}

            try:
                # 发送安装进度：开始克隆
                progress_msg = create_skill_install_progress_message(
                    spec=spec,
                    stage=SkillInstallStage.CLONING,
                    progress=10,
                    message="正在克隆 marketplace 仓库...",
                    session_id=session_id
                )
                await self.ws_manager.broadcast_to_session(
                    session_id, progress_msg
                )

                # 执行安装
                plugin = manager.install_plugin(spec, force=force)

                # 发送安装进度：复制完成
                progress_msg = create_skill_install_progress_message(
                    spec=spec,
                    stage=SkillInstallStage.REGISTERING,
                    progress=90,
                    message="正在注册插件...",
                    session_id=session_id
                )
                await self.ws_manager.broadcast_to_session(
                    session_id, progress_msg
                )

                plugin_data = {
                    "plugin_name": plugin.plugin_name,
                    "marketplace": plugin.marketplace,
                    "spec": plugin.spec,
                    "version": plugin.version,
                    "installed_at": plugin.installed_at.isoformat(),
                    "git_commit": plugin.git_commit,
                    "skills": plugin.skills
                }

                # 发送安装成功结果
                result_msg = create_skill_install_result_message(
                    action="install",
                    spec=spec,
                    success=True,
                    message=f"插件 {spec} 安装成功",
                    plugin=plugin_data,
                    session_id=session_id
                )
                await self.ws_manager.broadcast_to_session(
                    session_id, result_msg
                )

                # 广播更新后的 skill 列表
                skills = manager.list_skills()
                skills_data = [
                    {
                        "name": s.name,
                        "description": s.description,
                        "source": s.source.value,
                        "version": s.metadata.version,
                        "author": s.metadata.author,
                        "tags": s.metadata.tags,
                        "allowed_tools": list(s.allowed_tools)
                    }
                    for s in skills
                ]
                skill_update_msg = create_skill_update_message(
                    skills_data, session_id
                )
                await self.ws_manager.broadcast_to_session(
                    session_id, skill_update_msg
                )

                return {"success": True, "plugin": plugin_data}

            except (ValueError, RuntimeError) as e:
                # 发送安装失败结果
                result_msg = create_skill_install_result_message(
                    action="install",
                    spec=spec,
                    success=False,
                    message="安装失败",
                    error=str(e),
                    session_id=session_id
                )
                await self.ws_manager.broadcast_to_session(
                    session_id, result_msg
                )

                return {"success": False, "error": str(e)}

        elif action == "uninstall":
            if not spec:
                return {"success": False, "error": "spec 参数不能为空"}

            try:
                manager.uninstall_plugin(spec)

                # 发送卸载成功结果
                result_msg = create_skill_install_result_message(
                    action="uninstall",
                    spec=spec,
                    success=True,
                    message=f"插件 {spec} 卸载成功",
                    session_id=session_id
                )
                await self.ws_manager.broadcast_to_session(
                    session_id, result_msg
                )

                # 广播更新后的 skill 列表
                skills = manager.list_skills()
                skills_data = [
                    {
                        "name": s.name,
                        "description": s.description,
                        "source": s.source.value,
                        "version": s.metadata.version,
                        "author": s.metadata.author,
                        "tags": s.metadata.tags,
                        "allowed_tools": list(s.allowed_tools)
                    }
                    for s in skills
                ]
                skill_update_msg = create_skill_update_message(
                    skills_data, session_id
                )
                await self.ws_manager.broadcast_to_session(
                    session_id, skill_update_msg
                )

                return {"success": True}

            except ValueError as e:
                # 发送卸载失败结果
                result_msg = create_skill_install_result_message(
                    action="uninstall",
                    spec=spec,
                    success=False,
                    message="卸载失败",
                    error=str(e),
                    session_id=session_id
                )
                await self.ws_manager.broadcast_to_session(
                    session_id, result_msg
                )

                return {"success": False, "error": str(e)}

        else:
            return {"success": False, "error": f"未知操作: {action}"}


# 全局单例
_service: Optional[AgentService] = None


def get_agent_service() -> AgentService:
    """获取 Agent 服务单例"""
    global _service
    if _service is None:
        _service = AgentService()
    return _service
