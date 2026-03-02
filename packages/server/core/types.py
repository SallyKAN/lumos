"""
Lumos Core — 类型定义

富内容块消息模型 + 事件类型 + LLM 配置。
替代旧的扁平 Message 模型，支持多种内容块类型。
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional, Union


# ============================================================================
# 内容块类型
# ============================================================================

@dataclass
class TextContent:
    """文本内容块"""
    text: str
    type: str = "text"


@dataclass
class ThinkingContent:
    """思考内容块"""
    thinking: str
    type: str = "thinking"


@dataclass
class ImageContent:
    """图片内容块"""
    source: str
    media_type: str = "image/png"
    type: str = "image"


@dataclass
class ToolCallContent:
    """工具调用内容块"""
    id: str
    name: str
    arguments: dict[str, Any] = field(default_factory=dict)
    type: str = "tool_call"


ContentBlock = Union[TextContent, ThinkingContent, ImageContent, ToolCallContent]


# ============================================================================
# 消息类型
# ============================================================================

@dataclass
class UserMessage:
    """用户消息"""
    content: Union[str, list[ContentBlock]]
    role: str = "user"
    timestamp: float = field(default_factory=time.time)

    @property
    def text(self) -> str:
        if isinstance(self.content, str):
            return self.content
        return "".join(
            b.text for b in self.content if isinstance(b, TextContent)
        )


@dataclass
class AssistantMessage:
    """助手消息"""
    content: list[ContentBlock] = field(default_factory=list)
    role: str = "assistant"
    usage: Optional[dict[str, int]] = None
    stop_reason: Optional[str] = None
    model: Optional[str] = None
    provider: Optional[str] = None
    timestamp: float = field(default_factory=time.time)

    @property
    def text(self) -> str:
        return "".join(
            b.text for b in self.content if isinstance(b, TextContent)
        )

    @property
    def tool_calls(self) -> list[ToolCallContent]:
        return [b for b in self.content if isinstance(b, ToolCallContent)]


@dataclass
class ToolResultMessage:
    """工具结果消息"""
    tool_call_id: str
    tool_name: str
    content: list[ContentBlock] = field(default_factory=list)
    is_error: bool = False
    details: Any = None
    role: str = "tool_result"
    timestamp: float = field(default_factory=time.time)

    @property
    def text(self) -> str:
        return "".join(
            b.text for b in self.content if isinstance(b, TextContent)
        )


AgentMessage = Union[UserMessage, AssistantMessage, ToolResultMessage]


# ============================================================================
# LLM 配置（从旧 llm.py 迁入）
# ============================================================================

@dataclass
class LLMConfig:
    """LLM 配置"""
    provider: str  # "anthropic" | "openai" | "zhipu"
    model: str
    api_key: str
    api_base: Optional[str] = None
    temperature: float = 0.0
    max_tokens: int = 8192
    timeout: int = 120
    top_p: Optional[float] = None


# ============================================================================
# 事件类型
# ============================================================================

class AgentEventType(str, Enum):
    """Agent 事件类型"""
    AGENT_START = "agent_start"
    AGENT_END = "agent_end"
    TURN_START = "turn_start"
    TURN_END = "turn_end"
    MESSAGE_START = "message_start"
    MESSAGE_DELTA = "message_delta"
    MESSAGE_END = "message_end"
    TOOL_START = "tool_start"
    TOOL_UPDATE = "tool_update"
    TOOL_END = "tool_end"
    ERROR = "error"


@dataclass
class AgentEvent:
    """Agent 事件"""
    type: AgentEventType
    data: Any = None
    timestamp: float = field(default_factory=time.time)


# ============================================================================
# 循环配置
# ============================================================================

@dataclass
class AgentLoopConfig:
    """Agent 循环配置"""
    system_prompt: str = ""
    max_iterations: int = 100
    max_tokens: int = 8192
    temperature: float = 0.7
    top_p: Optional[float] = 0.9
