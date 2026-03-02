# 旧接口（兼容层）
from .tool import BaseTool, ToolParam, Tool, ToolInfo, Parameters, Param, LocalFunction  # noqa: F401

# 新接口（Pi Agent 风格）
from .types import (  # noqa: F401
    TextContent,
    ThinkingContent,
    ImageContent,
    ToolCallContent,
    ContentBlock,
    UserMessage,
    AssistantMessage,
    ToolResultMessage,
    AgentMessage,
    LLMConfig,
    AgentEventType,
    AgentEvent,
    AgentLoopConfig,
)
from .tool import AgentTool, AgentToolResult, wrap_legacy_tool  # noqa: F401
from .event_stream import EventStream  # noqa: F401
from .agent_loop import agent_loop  # noqa: F401
from .agent import Agent  # noqa: F401
from .stream_fn import StreamFn, stream_anthropic, stream_openai  # noqa: F401
from .convert import convert_to_anthropic, convert_to_openai  # noqa: F401
