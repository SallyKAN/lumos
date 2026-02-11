"""
WebSocket 消息协议定义

定义 Web UI 与后端之间的 WebSocket 消息格式和类型。
"""

from enum import Enum
from typing import Dict, Any, Optional, List
from dataclasses import dataclass, field
from datetime import datetime
import json


class MessageType(str, Enum):
    """WebSocket 消息类型枚举"""

    # 客户端 -> 服务端
    CHAT_MESSAGE = "chat_message"       # 用户发送消息
    INTERRUPT = "interrupt"              # 用户中断（等同于 Esc）
    SWITCH_MODE = "switch_mode"          # 切换模式
    TODO_ACTION = "todo_action"          # Todo 操作
    SESSION_ACTION = "session_action"    # 会话管理
    SKILL_ACTION = "skill_action"        # Skill 操作

    # 服务端 -> 客户端（映射自 AgentEvent）
    THINKING = "thinking"                # Agent 思考中
    CONTENT_CHUNK = "content_chunk"      # 流式内容块
    CONTENT = "content"                  # 完整内容
    MEDIA_CONTENT = "media_content"      # 包含媒体的内容
    TOOL_CALL = "tool_call"              # 工具调用开始
    TOOL_RESULT = "tool_result"          # 工具执行结果
    ERROR = "error"                      # 错误
    MODE_CHANGE = "mode_change"          # 模式变更
    INTERRUPT_RESULT = "interrupt_result"  # 中断处理结果
    SUBTASK_UPDATE = "subtask_update"    # 子任务进度更新

    # Skills 相关（服务端 -> 客户端）
    SKILL_UPDATE = "skill_update"                    # Skill 列表更新
    SKILL_INSTALL_PROGRESS = "skill_install_progress"  # 安装进度
    SKILL_INSTALL_RESULT = "skill_install_result"    # 安装/卸载结果

    # 用户交互（双向）
    ASK_USER_QUESTION = "ask_user_question"          # 服务端 -> 客户端：请求用户回答问题
    USER_ANSWER = "user_answer"                      # 客户端 -> 服务端：用户回答

    # 双向
    TODO_UPDATE = "todo_update"          # Todo 列表更新
    SESSION_UPDATE = "session_update"    # 会话状态更新
    CONNECTION_ACK = "connection_ack"    # 连接确认
    HEARTBEAT = "heartbeat"              # 心跳
    PROCESSING_STATUS = "processing_status"  # 处理状态


class InterruptIntent(str, Enum):
    """中断意图类型"""
    SWITCH = "switch"           # 切换到新任务
    PAUSE = "pause"             # 暂停当前任务
    CANCEL = "cancel"           # 取消当前任务
    SUPPLEMENT = "supplement"   # 补充信息
    RESUME = "resume"           # 恢复暂停的任务


class TodoAction(str, Enum):
    """Todo 操作类型"""
    CREATE = "create"
    UPDATE = "update"
    LIST = "list"
    CLEAR = "clear"


class SessionAction(str, Enum):
    """会话操作类型"""
    CREATE = "create"
    RESUME = "resume"
    PAUSE = "pause"
    DELETE = "delete"
    LIST = "list"


class SkillAction(str, Enum):
    """Skill 操作类型"""
    LIST = "list"                    # 列出所有 skills
    LIST_INSTALLED = "list_installed"  # 列出已安装插件
    INSTALL = "install"              # 安装插件
    UNINSTALL = "uninstall"          # 卸载插件


class SkillInstallStage(str, Enum):
    """Skill 安装阶段"""
    CLONING = "cloning"              # 克隆 marketplace 仓库
    COPYING = "copying"              # 复制 skills 文件
    REGISTERING = "registering"      # 注册插件信息


@dataclass
class WebSocketMessage:
    """WebSocket 消息基类"""
    type: MessageType
    payload: Dict[str, Any] = field(default_factory=dict)
    session_id: Optional[str] = None
    message_id: Optional[str] = None
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "type": self.type.value if isinstance(self.type, MessageType) else self.type,
            "payload": self.payload,
            "session_id": self.session_id,
            "message_id": self.message_id,
            "timestamp": self.timestamp
        }

    def to_json(self) -> str:
        """转换为 JSON 字符串"""
        return json.dumps(self.to_dict(), ensure_ascii=False)

    @staticmethod
    def from_dict(data: Dict[str, Any]) -> 'WebSocketMessage':
        """从字典创建实例"""
        msg_type = data.get("type", "")
        try:
            msg_type = MessageType(msg_type)
        except ValueError:
            pass  # 保持字符串形式

        return WebSocketMessage(
            type=msg_type,
            payload=data.get("payload", {}),
            session_id=data.get("session_id"),
            message_id=data.get("message_id"),
            timestamp=data.get("timestamp", datetime.now().isoformat())
        )

    @staticmethod
    def from_json(json_str: str) -> 'WebSocketMessage':
        """从 JSON 字符串创建实例"""
        data = json.loads(json_str)
        return WebSocketMessage.from_dict(data)


# ============================================================================
# Payload 数据类
# ============================================================================

@dataclass
class ChatMessagePayload:
    """聊天消息 Payload"""
    content: str
    conversation_id: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {"content": self.content, "conversation_id": self.conversation_id}


@dataclass
class ToolCallPayload:
    """工具调用 Payload"""
    id: str
    name: str
    arguments: Dict[str, Any] = field(default_factory=dict)
    description: str = ""  # 操作描述，如 "创建 3 个任务"
    formatted_args: str = ""  # 格式化参数摘要

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "arguments": self.arguments,
            "description": self.description,
            "formatted_args": self.formatted_args
        }


@dataclass
class ToolResultPayload:
    """工具结果 Payload"""
    tool_name: str
    result: str
    success: bool = True
    tool_call_id: Optional[str] = None
    summary: str = ""  # 结果摘要

    def to_dict(self) -> Dict[str, Any]:
        return {
            "tool_name": self.tool_name,
            "result": self.result,
            "success": self.success,
            "tool_call_id": self.tool_call_id,
            "summary": self.summary
        }


@dataclass
class InterruptPayload:
    """中断 Payload

    前端只需发送 new_input（可选），意图由后端 IntentClassifier 自动判断。
    intent 字段为可选，用于后端处理后返回给前端的结果。
    """
    new_input: Optional[str] = None
    intent: Optional[InterruptIntent] = None  # 由后端填充，前端不需要发送

    def to_dict(self) -> Dict[str, Any]:
        result = {"new_input": self.new_input}
        if self.intent is not None:
            result["intent"] = (
                self.intent.value
                if isinstance(self.intent, InterruptIntent)
                else self.intent
            )
        return result


@dataclass
class TodoUpdatePayload:
    """Todo 更新 Payload"""
    action: TodoAction
    todos: Optional[List[Dict[str, Any]]] = None
    task_id: Optional[str] = None
    status: Optional[str] = None
    tasks: Optional[str] = None  # 简化格式的任务字符串

    def to_dict(self) -> Dict[str, Any]:
        return {
            "action": self.action.value if isinstance(self.action, TodoAction) else self.action,
            "todos": self.todos,
            "task_id": self.task_id,
            "status": self.status,
            "tasks": self.tasks
        }


@dataclass
class SessionUpdatePayload:
    """会话更新 Payload"""
    action: SessionAction
    session_id: Optional[str] = None
    project_path: Optional[str] = None
    title: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "action": self.action.value if isinstance(self.action, SessionAction) else self.action,
            "session_id": self.session_id,
            "project_path": self.project_path,
            "title": self.title
        }


@dataclass
class ModeChangePayload:
    """模式变更 Payload"""
    mode: str  # BUILD/PLAN/REVIEW
    previous_mode: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {"mode": self.mode, "previous_mode": self.previous_mode}


@dataclass
class ProcessingStatusPayload:
    """处理状态 Payload"""
    is_processing: bool
    current_task: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {"is_processing": self.is_processing, "current_task": self.current_task}


@dataclass
class ConnectionAckPayload:
    """连接确认 Payload"""
    session_id: str
    mode: str
    tools: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {"session_id": self.session_id, "mode": self.mode, "tools": self.tools}


@dataclass
class ErrorPayload:
    """错误 Payload"""
    error: str
    code: Optional[str] = None
    recoverable: bool = True

    def to_dict(self) -> Dict[str, Any]:
        return {"error": self.error, "code": self.code, "recoverable": self.recoverable}


@dataclass
class InterruptResultPayload:
    """中断结果 Payload

    后端处理中断请求后返回给前端的结果。
    """
    intent: str                         # switch/pause/cancel/supplement/resume
    success: bool = True
    message: str = ""                   # 显示给用户的消息
    new_input: Optional[str] = None     # 用于 switch 的新输入
    merged_input: Optional[str] = None  # 用于 supplement 的合并输入
    paused_task: Optional[str] = None   # 暂停的任务描述

    def to_dict(self) -> Dict[str, Any]:
        return {
            "intent": self.intent,
            "success": self.success,
            "message": self.message,
            "new_input": self.new_input,
            "merged_input": self.merged_input,
            "paused_task": self.paused_task
        }


# ============================================================================
# 用户问题相关 Payload 数据类
# ============================================================================

@dataclass
class QuestionOptionPayload:
    """问题选项 Payload"""
    label: str
    description: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {"label": self.label, "description": self.description}


@dataclass
class QuestionPayload:
    """问题 Payload"""
    question: str
    header: str
    options: List[Dict[str, Any]] = field(default_factory=list)
    multi_select: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "question": self.question,
            "header": self.header,
            "options": self.options,
            "multi_select": self.multi_select
        }


@dataclass
class AskUserQuestionPayload:
    """用户问题请求 Payload（服务端 -> 客户端）"""
    request_id: str                     # 唯一请求 ID，用于匹配回答
    questions: List[Dict[str, Any]]     # 问题列表

    def to_dict(self) -> Dict[str, Any]:
        return {
            "request_id": self.request_id,
            "questions": self.questions
        }


@dataclass
class UserAnswerPayload:
    """用户回答 Payload（客户端 -> 服务端）"""
    request_id: str                     # 对应的请求 ID
    answers: List[Dict[str, Any]]       # 回答列表

    def to_dict(self) -> Dict[str, Any]:
        return {
            "request_id": self.request_id,
            "answers": self.answers
        }


# ============================================================================
# Skills 相关 Payload 数据类
# ============================================================================

@dataclass
class SubtaskUpdatePayload:
    """子任务进度更新 Payload"""
    task_id: str                         # 子任务 ID（用于前端匹配）
    description: str                     # 任务描述
    status: str                          # 状态: starting, tool_call, tool_result, completed, error
    index: int                           # 任务索引（从 0 开始）
    total: int                           # 总任务数
    tool_name: Optional[str] = None      # 当前工具名称（tool_call/tool_result 时）
    tool_count: int = 0                  # 已调用工具次数
    message: Optional[str] = None        # 附加消息（如工具结果摘要）
    is_parallel: bool = False            # 是否是并行任务

    def to_dict(self) -> Dict[str, Any]:
        return {
            "task_id": self.task_id,
            "description": self.description,
            "status": self.status,
            "index": self.index,
            "total": self.total,
            "tool_name": self.tool_name,
            "tool_count": self.tool_count,
            "message": self.message,
            "is_parallel": self.is_parallel
        }


@dataclass
class SkillActionPayload:
    """Skill 操作 Payload（客户端 -> 服务端）"""
    action: SkillAction
    spec: Optional[str] = None         # 安装/卸载时的插件规格
    force: bool = False                # 安装时是否强制重装

    def to_dict(self) -> Dict[str, Any]:
        return {
            "action": (
                self.action.value
                if isinstance(self.action, SkillAction)
                else self.action
            ),
            "spec": self.spec,
            "force": self.force
        }


@dataclass
class SkillItemPayload:
    """Skill 项数据"""
    name: str
    description: str
    source: str                        # local, project, marketplace
    version: str
    author: str
    tags: List[str] = field(default_factory=list)
    allowed_tools: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "source": self.source,
            "version": self.version,
            "author": self.author,
            "tags": self.tags,
            "allowed_tools": self.allowed_tools
        }


@dataclass
class InstalledPluginPayload:
    """已安装插件数据"""
    plugin_name: str
    marketplace: str
    spec: str
    version: str
    installed_at: str
    git_commit: Optional[str] = None
    skills: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "plugin_name": self.plugin_name,
            "marketplace": self.marketplace,
            "spec": self.spec,
            "version": self.version,
            "installed_at": self.installed_at,
            "git_commit": self.git_commit,
            "skills": self.skills
        }


@dataclass
class SkillUpdatePayload:
    """Skill 列表更新 Payload（服务端 -> 客户端）"""
    skills: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {"skills": self.skills}


@dataclass
class SkillInstallProgressPayload:
    """Skill 安装进度 Payload（服务端 -> 客户端）"""
    spec: str                          # 插件规格
    stage: SkillInstallStage           # 当前阶段
    progress: int                      # 进度百分比 (0-100)
    message: str                       # 进度描述

    def to_dict(self) -> Dict[str, Any]:
        return {
            "spec": self.spec,
            "stage": (
                self.stage.value
                if isinstance(self.stage, SkillInstallStage)
                else self.stage
            ),
            "progress": self.progress,
            "message": self.message
        }


@dataclass
class SkillInstallResultPayload:
    """Skill 安装/卸载结果 Payload（服务端 -> 客户端）"""
    action: str                        # install/uninstall
    spec: str                          # 插件规格
    success: bool
    message: str
    plugin: Optional[Dict[str, Any]] = None  # 安装成功时返回插件信息
    error: Optional[str] = None        # 失败时的错误信息

    def to_dict(self) -> Dict[str, Any]:
        return {
            "action": self.action,
            "spec": self.spec,
            "success": self.success,
            "message": self.message,
            "plugin": self.plugin,
            "error": self.error
        }


# ============================================================================
# 消息工厂函数
# ============================================================================

def create_message(
    msg_type: MessageType,
    payload: Dict[str, Any],
    session_id: Optional[str] = None,
    message_id: Optional[str] = None
) -> WebSocketMessage:
    """创建 WebSocket 消息"""
    return WebSocketMessage(
        type=msg_type,
        payload=payload,
        session_id=session_id,
        message_id=message_id
    )


def create_content_chunk_message(
    content: str,
    session_id: Optional[str] = None
) -> WebSocketMessage:
    """创建流式内容块消息"""
    return create_message(
        MessageType.CONTENT_CHUNK,
        {"content": content},
        session_id
    )


def create_tool_call_message(
    tool_name: str,
    arguments: Dict[str, Any],
    tool_id: str,
    session_id: Optional[str] = None,
    description: str = "",
    formatted_args: str = ""
) -> WebSocketMessage:
    """创建工具调用消息"""
    return create_message(
        MessageType.TOOL_CALL,
        ToolCallPayload(
            id=tool_id,
            name=tool_name,
            arguments=arguments,
            description=description,
            formatted_args=formatted_args
        ).to_dict(),
        session_id
    )


def create_tool_result_message(
    tool_name: str,
    result: str,
    success: bool = True,
    session_id: Optional[str] = None,
    tool_call_id: Optional[str] = None,
    summary: str = ""
) -> WebSocketMessage:
    """创建工具结果消息"""
    return create_message(
        MessageType.TOOL_RESULT,
        ToolResultPayload(
            tool_name=tool_name,
            result=result,
            success=success,
            tool_call_id=tool_call_id,
            summary=summary
        ).to_dict(),
        session_id
    )


def create_error_message(
    error: str,
    code: Optional[str] = None,
    recoverable: bool = True,
    session_id: Optional[str] = None
) -> WebSocketMessage:
    """创建错误消息"""
    return create_message(
        MessageType.ERROR,
        ErrorPayload(error=error, code=code, recoverable=recoverable).to_dict(),
        session_id
    )


def create_todo_update_message(
    todos: List[Dict[str, Any]],
    session_id: Optional[str] = None
) -> WebSocketMessage:
    """创建 Todo 更新消息"""
    return create_message(
        MessageType.TODO_UPDATE,
        {"todos": todos},
        session_id
    )


def create_mode_change_message(
    mode: str,
    previous_mode: Optional[str] = None,
    session_id: Optional[str] = None
) -> WebSocketMessage:
    """创建模式变更消息"""
    return create_message(
        MessageType.MODE_CHANGE,
        ModeChangePayload(mode=mode, previous_mode=previous_mode).to_dict(),
        session_id
    )


def create_processing_status_message(
    is_processing: bool,
    current_task: Optional[str] = None,
    session_id: Optional[str] = None
) -> WebSocketMessage:
    """创建处理状态消息"""
    return create_message(
        MessageType.PROCESSING_STATUS,
        ProcessingStatusPayload(is_processing=is_processing, current_task=current_task).to_dict(),
        session_id
    )


def create_connection_ack_message(
    session_id: str,
    mode: str,
    tools: List[str]
) -> WebSocketMessage:
    """创建连接确认消息"""
    return create_message(
        MessageType.CONNECTION_ACK,
        ConnectionAckPayload(session_id=session_id, mode=mode, tools=tools).to_dict(),
        session_id
    )


def create_interrupt_result_message(
    intent: str,
    success: bool = True,
    message: str = "",
    new_input: Optional[str] = None,
    merged_input: Optional[str] = None,
    paused_task: Optional[str] = None,
    session_id: Optional[str] = None
) -> WebSocketMessage:
    """创建中断结果消息"""
    return create_message(
        MessageType.INTERRUPT_RESULT,
        InterruptResultPayload(
            intent=intent,
            success=success,
            message=message,
            new_input=new_input,
            merged_input=merged_input,
            paused_task=paused_task
        ).to_dict(),
        session_id
    )


# ============================================================================
# 子任务消息工厂函数
# ============================================================================

def create_subtask_update_message(
    task_id: str,
    description: str,
    status: str,
    index: int,
    total: int,
    tool_name: Optional[str] = None,
    tool_count: int = 0,
    message: Optional[str] = None,
    is_parallel: bool = False,
    session_id: Optional[str] = None
) -> WebSocketMessage:
    """创建子任务进度更新消息"""
    return create_message(
        MessageType.SUBTASK_UPDATE,
        SubtaskUpdatePayload(
            task_id=task_id,
            description=description,
            status=status,
            index=index,
            total=total,
            tool_name=tool_name,
            tool_count=tool_count,
            message=message,
            is_parallel=is_parallel
        ).to_dict(),
        session_id
    )


# ============================================================================
# Skills 消息工厂函数
# ============================================================================

def create_skill_update_message(
    skills: List[Dict[str, Any]],
    session_id: Optional[str] = None
) -> WebSocketMessage:
    """创建 Skill 列表更新消息"""
    return create_message(
        MessageType.SKILL_UPDATE,
        SkillUpdatePayload(skills=skills).to_dict(),
        session_id
    )


def create_skill_install_progress_message(
    spec: str,
    stage: SkillInstallStage,
    progress: int,
    message: str,
    session_id: Optional[str] = None
) -> WebSocketMessage:
    """创建 Skill 安装进度消息"""
    return create_message(
        MessageType.SKILL_INSTALL_PROGRESS,
        SkillInstallProgressPayload(
            spec=spec,
            stage=stage,
            progress=progress,
            message=message
        ).to_dict(),
        session_id
    )


def create_skill_install_result_message(
    action: str,
    spec: str,
    success: bool,
    message: str,
    plugin: Optional[Dict[str, Any]] = None,
    error: Optional[str] = None,
    session_id: Optional[str] = None
) -> WebSocketMessage:
    """创建 Skill 安装/卸载结果消息"""
    return create_message(
        MessageType.SKILL_INSTALL_RESULT,
        SkillInstallResultPayload(
            action=action,
            spec=spec,
            success=success,
            message=message,
            plugin=plugin,
            error=error
        ).to_dict(),
        session_id
    )


# ============================================================================
# 用户问题消息工厂函数
# ============================================================================

def create_ask_user_question_message(
    request_id: str,
    questions: List[Dict[str, Any]],
    session_id: Optional[str] = None
) -> WebSocketMessage:
    """创建用户问题请求消息"""
    return create_message(
        MessageType.ASK_USER_QUESTION,
        AskUserQuestionPayload(
            request_id=request_id,
            questions=questions
        ).to_dict(),
        session_id
    )
