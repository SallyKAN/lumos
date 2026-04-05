"""
Lumos Interceptor — 类型定义

拦截器系统的所有数据类型。复用 core.types 中的现有类型。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from ..core.tool import AgentTool
    from ..core.types import (
        AgentMessage,
        AssistantMessage,
        ContentBlock,
        LLMConfig,
        AgentLoopConfig,
    )


# ============================================================================
# Agent 上下文
# ============================================================================

@dataclass
class AgentContext:
    """Agent 运行上下文，贯穿整个 session"""
    messages: list[AgentMessage]
    tools: list[AgentTool]
    llm_config: LLMConfig
    loop_config: AgentLoopConfig
    iteration: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)


# ============================================================================
# Model 拦截点类型
# ============================================================================

@dataclass
class ModelRequest:
    """before_model / wrap_model 的输入"""
    messages: list[AgentMessage]
    system_prompt: str
    tools: list[AgentTool]
    llm_config: LLMConfig
    metadata: dict[str, Any] = field(default_factory=dict)

    def with_overrides(self, **kwargs) -> ModelRequest:
        """返回新对象，覆盖指定字段"""
        from dataclasses import replace
        return replace(self, **kwargs)


@dataclass
class ModelResponse:
    """after_model 的输入"""
    message: AssistantMessage
    request: ModelRequest
    metadata: dict[str, Any] = field(default_factory=dict)


# ============================================================================
# Tool 拦截点类型
# ============================================================================

@dataclass
class ToolRequest:
    """pre_tool_use / wrap_tool 的输入"""
    tool_call_id: str
    tool_name: str
    arguments: dict[str, Any]
    tool: Optional[AgentTool] = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ToolResult:
    """post_tool_use 的输入"""
    tool_call_id: str
    tool_name: str
    content: list[ContentBlock] = field(default_factory=list)
    is_error: bool = False
    details: Any = None
    request: Optional[ToolRequest] = None
    metadata: dict[str, Any] = field(default_factory=dict)


# ============================================================================
# Stop 拦截点类型
# ============================================================================

@dataclass
class StopContext:
    """stop / subagent_stop 的输入"""
    reason: str  # "no_tool_calls" | "max_iterations" | "abort" | "subagent_done"
    messages: list[AgentMessage] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class StopDecision:
    """stop / subagent_stop 的输出"""
    should_stop: bool = True
    inject_messages: list[AgentMessage] = field(default_factory=list)
    reason: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


# ============================================================================
# Error 拦截点类型
# ============================================================================

@dataclass
class AgentError:
    """error 拦截点的输入"""
    exception: Exception
    phase: str  # "model" | "tool" | "loop"
    context: Optional[AgentContext] = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ErrorRecovery:
    """error 拦截点的输出"""
    handled: bool = False
    retry: bool = False
    inject_messages: list[AgentMessage] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
