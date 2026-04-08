"""
Lumos Core — 消息转换

内部 AgentMessage 与 LLM API 格式之间的双向转换。
只在 LLM 调用边界使用。
"""

from __future__ import annotations

import json
from typing import Any

from .types import (
    AgentMessage,
    AssistantMessage,
    ContentBlock,
    ImageContent,
    LLMConfig,
    TextContent,
    ThinkingContent,
    ToolCallContent,
    ToolResultMessage,
    UserMessage,
)


# ============================================================================
# 内部 → Anthropic API
# ============================================================================

def convert_to_anthropic(
    messages: list[AgentMessage],
    system_prompt: str = "",
) -> tuple[str, list[dict[str, Any]]]:
    """将内部消息转换为 Anthropic API 格式

    Returns:
        (system_str, api_messages)
    """
    api_messages: list[dict[str, Any]] = []

    for msg in messages:
        if isinstance(msg, UserMessage):
            if isinstance(msg.content, str):
                api_messages.append({"role": "user", "content": msg.content})
            else:
                api_messages.append({
                    "role": "user",
                    "content": _blocks_to_anthropic(msg.content),
                })

        elif isinstance(msg, AssistantMessage):
            content = _blocks_to_anthropic(msg.content)
            if content:
                api_messages.append({"role": "assistant", "content": content})

        elif isinstance(msg, ToolResultMessage):
            result_content = msg.text if msg.content else ""
            api_messages.append({
                "role": "user",
                "content": [{
                    "type": "tool_result",
                    "tool_use_id": msg.tool_call_id,
                    "content": result_content,
                    **({"is_error": True} if msg.is_error else {}),
                }],
            })

    return system_prompt, api_messages


def _blocks_to_anthropic(blocks: list[ContentBlock]) -> list[dict[str, Any]]:
    """将内容块列表转换为 Anthropic content 数组"""
    result = []
    for b in blocks:
        if isinstance(b, TextContent):
            if b.text:
                result.append({"type": "text", "text": b.text})
        elif isinstance(b, ThinkingContent):
            if b.thinking:
                result.append({"type": "thinking", "thinking": b.thinking})
        elif isinstance(b, ToolCallContent):
            result.append({
                "type": "tool_use",
                "id": b.id,
                "name": b.name,
                "input": b.arguments,
            })
        elif isinstance(b, ImageContent):
            result.append({
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": b.media_type,
                    "data": b.source,
                },
            })
    return result


# ============================================================================
# 内部 → OpenAI API
# ============================================================================

def convert_to_openai(
    messages: list[AgentMessage],
    system_prompt: str = "",
) -> list[dict[str, Any]]:
    """将内部消息转换为 OpenAI API 格式"""
    api_messages: list[dict[str, Any]] = []

    if system_prompt:
        api_messages.append({"role": "system", "content": system_prompt})

    for msg in messages:
        if isinstance(msg, UserMessage):
            text = msg.text if not isinstance(msg.content, str) else msg.content
            api_messages.append({"role": "user", "content": text})

        elif isinstance(msg, AssistantMessage):
            d: dict[str, Any] = {"role": "assistant", "content": msg.text or None}
            tool_calls = msg.tool_calls
            if tool_calls:
                d["tool_calls"] = [{
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.name,
                        "arguments": json.dumps(tc.arguments),
                    },
                } for tc in tool_calls]
            api_messages.append(d)

        elif isinstance(msg, ToolResultMessage):
            api_messages.append({
                "role": "tool",
                "tool_call_id": msg.tool_call_id,
                "content": msg.text,
            })

    return api_messages


# ============================================================================
# 统一分发
# ============================================================================

def convert_to_llm(
    messages: list[AgentMessage],
    config: LLMConfig,
    system_prompt: str = "",
) -> dict[str, Any]:
    """根据 provider 分发到对应转换函数

    Returns:
        对于 anthropic: {"system": str, "messages": list}
        对于 openai:    {"messages": list}
    """
    if config.provider == "anthropic":
        system_str, api_msgs = convert_to_anthropic(messages, system_prompt)
        return {"system": system_str, "messages": api_msgs}
    else:
        api_msgs = convert_to_openai(messages, system_prompt)
        return {"messages": api_msgs}
