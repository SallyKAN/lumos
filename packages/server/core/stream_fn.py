"""
Lumos Core — 可注入 LLM 流函数

定义 StreamFn 协议，提供 Anthropic 和 OpenAI 的内置实现。
stream_fn 负责：调用 LLM API → 解析响应 → 推送事件到 EventStream → 返回 AssistantMessage。
"""

from __future__ import annotations

import json
import logging
from typing import Any, Protocol

from .convert import convert_to_anthropic, convert_to_openai
from .event_stream import EventStream
from .tool import AgentTool
from .types import (
    AgentEvent,
    AgentEventType,
    AssistantMessage,
    AgentMessage,
    LLMConfig,
    TextContent,
    ThinkingContent,
    ToolCallContent,
)

logger = logging.getLogger(__name__)


class StreamFn(Protocol):
    """LLM 流函数协议"""

    async def __call__(
        self,
        messages: list[AgentMessage],
        config: LLMConfig,
        system_prompt: str,
        tools: list[AgentTool],
        event_stream: EventStream[AgentEvent],
    ) -> AssistantMessage: ...


# ============================================================================
# Anthropic 实现
# ============================================================================

async def stream_anthropic(
    messages: list[AgentMessage],
    config: LLMConfig,
    system_prompt: str,
    tools: list[AgentTool],
    event_stream: EventStream[AgentEvent],
) -> AssistantMessage:
    """Anthropic 流式调用"""
    import anthropic

    client_kwargs: dict[str, Any] = {
        "api_key": config.api_key,
        "timeout": config.timeout,
    }
    if config.api_base:
        client_kwargs["base_url"] = config.api_base

    client = anthropic.AsyncAnthropic(**client_kwargs)

    system_str, api_messages = convert_to_anthropic(messages, system_prompt)

    kwargs: dict[str, Any] = {
        "model": config.model,
        "max_tokens": config.max_tokens,
        "messages": api_messages,
    }
    if system_str:
        kwargs["system"] = system_str
    if tools:
        kwargs["tools"] = [t.to_anthropic_schema() for t in tools]
    if config.temperature is not None:
        kwargs["temperature"] = config.temperature

    content_blocks: list = []
    text_parts: list[str] = []

    event_stream.push(AgentEvent(type=AgentEventType.MESSAGE_START))

    async with client.messages.stream(**kwargs) as stream:
        current_tool_name = ""
        current_tool_id = ""
        current_tool_json = ""
        in_tool = False

        async for event in stream:
            if event.type == "content_block_start":
                block = event.content_block
                if hasattr(block, "type"):
                    if block.type == "tool_use":
                        in_tool = True
                        current_tool_name = block.name
                        current_tool_id = block.id
                        current_tool_json = ""
                    elif block.type == "thinking":
                        pass

            elif event.type == "content_block_delta":
                delta = event.delta
                if hasattr(delta, "type"):
                    if delta.type == "text_delta":
                        text_parts.append(delta.text)
                        event_stream.push(AgentEvent(
                            type=AgentEventType.MESSAGE_DELTA,
                            data={"type": "text", "text": delta.text},
                        ))
                    elif delta.type == "thinking_delta":
                        event_stream.push(AgentEvent(
                            type=AgentEventType.MESSAGE_DELTA,
                            data={"type": "thinking", "thinking": delta.thinking},
                        ))
                    elif delta.type == "input_json_delta":
                        current_tool_json += delta.partial_json

            elif event.type == "content_block_stop":
                if in_tool:
                    try:
                        args = json.loads(current_tool_json) if current_tool_json else {}
                    except json.JSONDecodeError:
                        args = {}
                    tc = ToolCallContent(
                        id=current_tool_id,
                        name=current_tool_name,
                        arguments=args,
                    )
                    content_blocks.append(tc)
                    in_tool = False

    # 构建最终文本块
    if text_parts:
        content_blocks.insert(0, TextContent(text="".join(text_parts)))

    # 提取 usage / stop_reason
    usage = None
    stop_reason = None
    final_message = getattr(stream, "get_final_message", None)
    if callable(final_message):
        try:
            final = await final_message()  # type: ignore[misc]
            if hasattr(final, "usage"):
                u = final.usage
                usage = {"input_tokens": u.input_tokens, "output_tokens": u.output_tokens}
            if hasattr(final, "stop_reason"):
                stop_reason = final.stop_reason
        except Exception:
            pass

    assistant_msg = AssistantMessage(
        content=content_blocks,
        usage=usage,
        stop_reason=stop_reason,
        model=config.model,
        provider=config.provider,
    )

    event_stream.push(AgentEvent(type=AgentEventType.MESSAGE_END, data=assistant_msg))
    return assistant_msg


# ============================================================================
# OpenAI 实现（非流式 fallback）
# ============================================================================

async def stream_openai(
    messages: list[AgentMessage],
    config: LLMConfig,
    system_prompt: str,
    tools: list[AgentTool],
    event_stream: EventStream[AgentEvent],
) -> AssistantMessage:
    """OpenAI 兼容调用（非流式 fallback）"""
    import openai

    client_kwargs: dict[str, Any] = {
        "api_key": config.api_key,
        "timeout": config.timeout,
    }
    if config.api_base:
        client_kwargs["base_url"] = config.api_base

    client = openai.AsyncOpenAI(**client_kwargs)

    api_messages = convert_to_openai(messages, system_prompt)

    kwargs: dict[str, Any] = {
        "model": config.model,
        "messages": api_messages,
        "max_tokens": config.max_tokens,
    }
    if tools:
        kwargs["tools"] = [t.to_openai_schema() for t in tools]
    if config.temperature is not None:
        kwargs["temperature"] = config.temperature

    event_stream.push(AgentEvent(type=AgentEventType.MESSAGE_START))

    response = await client.chat.completions.create(**kwargs)
    choice = response.choices[0]
    msg = choice.message

    content_blocks: list = []
    text = msg.content or ""

    if text:
        content_blocks.append(TextContent(text=text))
        event_stream.push(AgentEvent(
            type=AgentEventType.MESSAGE_DELTA,
            data={"type": "text", "text": text},
        ))

    if msg.tool_calls:
        for tc in msg.tool_calls:
            try:
                args = json.loads(tc.function.arguments)
            except json.JSONDecodeError:
                args = {}
            content_blocks.append(ToolCallContent(
                id=tc.id,
                name=tc.function.name,
                arguments=args,
            ))

    usage = None
    if hasattr(response, "usage") and response.usage:
        u = response.usage
        usage = {
            "input_tokens": getattr(u, "prompt_tokens", 0),
            "output_tokens": getattr(u, "completion_tokens", 0),
        }

    assistant_msg = AssistantMessage(
        content=content_blocks,
        usage=usage,
        stop_reason=getattr(choice, "finish_reason", None),
        model=config.model,
        provider=config.provider,
    )

    event_stream.push(AgentEvent(type=AgentEventType.MESSAGE_END, data=assistant_msg))
    return assistant_msg


# ============================================================================
# 工厂函数
# ============================================================================

def get_default_stream_fn(config: LLMConfig) -> StreamFn:
    """根据 provider 返回默认的流函数"""
    if config.provider == "anthropic":
        return stream_anthropic  # type: ignore[return-value]
    return stream_openai  # type: ignore[return-value]
