"""
Lumos Core — LLM 抽象层

替代 openJiuwen SDK 的 BaseModelInfo, ModelConfig。
提供统一的 LLM 配置和消息格式。
"""

from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class LLMConfig:
    """LLM 配置，替代 SDK 的 BaseModelInfo + ModelConfig"""
    provider: str  # "anthropic" | "openai" | "zhipu"
    model: str
    api_key: str
    api_base: Optional[str] = None
    temperature: float = 0.0
    max_tokens: int = 8192
    timeout: int = 120
    top_p: Optional[float] = None


@dataclass
class ToolCall:
    """工具调用"""
    id: str
    name: str
    arguments: dict[str, Any] = field(default_factory=dict)


@dataclass
class Message:
    """对话消息"""
    role: str  # "system" | "user" | "assistant" | "tool"
    content: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    tool_call_id: Optional[str] = None
    name: Optional[str] = None

    def to_dict(self) -> dict:
        d: dict[str, Any] = {"role": self.role, "content": self.content}
        if self.tool_calls:
            d["tool_calls"] = [
                {"id": tc.id, "name": tc.name, "arguments": tc.arguments}
                for tc in self.tool_calls
            ]
        if self.tool_call_id:
            d["tool_call_id"] = self.tool_call_id
        if self.name:
            d["name"] = self.name
        return d

    @classmethod
    def user(cls, content: str) -> "Message":
        return cls(role="user", content=content)

    @classmethod
    def assistant(cls, content: str, tool_calls: list[ToolCall] | None = None) -> "Message":
        return cls(role="assistant", content=content, tool_calls=tool_calls or [])

    @classmethod
    def system(cls, content: str) -> "Message":
        return cls(role="system", content=content)

    @classmethod
    def tool_result(cls, tool_call_id: str, content: str, name: str = "") -> "Message":
        return cls(role="tool", content=content, tool_call_id=tool_call_id, name=name)
