"""
Lumos Core — 纯函数 Agent Loop

Pi Agent 风格的双层循环：
- 外层：follow-up 消息驱动继续
- 内层：tool call + steering 消息处理
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Optional

from .event_stream import EventStream
from .stream_fn import StreamFn, get_default_stream_fn
from .tool import AgentTool, AgentToolResult
from .types import (
    AgentEvent,
    AgentEventType,
    AgentLoopConfig,
    AgentMessage,
    AssistantMessage,
    LLMConfig,
    TextContent,
    ToolCallContent,
    ToolResultMessage,
)

logger = logging.getLogger(__name__)


async def agent_loop(
    messages: list[AgentMessage],
    tools: list[AgentTool],
    llm_config: LLMConfig,
    loop_config: AgentLoopConfig,
    stream_fn: Optional[StreamFn] = None,
    abort_signal: Optional[Callable[[], bool]] = None,
    get_steering_messages: Optional[Callable[[], list[AgentMessage]]] = None,
    get_follow_up_messages: Optional[Callable[[], list[AgentMessage]]] = None,
) -> EventStream[AgentEvent]:
    """纯函数 agent loop

    Args:
        messages: 初始消息列表（会被修改）
        tools: 可用工具列表
        llm_config: LLM 配置
        loop_config: 循环配置
        stream_fn: LLM 流函数（可注入，默认根据 provider 选择）
        abort_signal: 中止信号（返回 True 时停止）
        get_steering_messages: 每次工具执行后检查，有消息则跳过剩余工具
        get_follow_up_messages: agent 即将停止前检查，有消息则继续

    Returns:
        EventStream 异步事件流
    """
    event_stream: EventStream[AgentEvent] = EventStream()

    if stream_fn is None:
        stream_fn = get_default_stream_fn(llm_config)

    tool_map = {t.name: t for t in tools}

    import asyncio
    asyncio.create_task(_run_loop(
        messages=messages,
        tool_map=tool_map,
        tools=tools,
        llm_config=llm_config,
        loop_config=loop_config,
        stream_fn=stream_fn,
        event_stream=event_stream,
        abort_signal=abort_signal,
        get_steering_messages=get_steering_messages,
        get_follow_up_messages=get_follow_up_messages,
    ))

    return event_stream


async def _run_loop(
    messages: list[AgentMessage],
    tool_map: dict[str, AgentTool],
    tools: list[AgentTool],
    llm_config: LLMConfig,
    loop_config: AgentLoopConfig,
    stream_fn: StreamFn,
    event_stream: EventStream[AgentEvent],
    abort_signal: Optional[Callable[[], bool]],
    get_steering_messages: Optional[Callable[[], list[AgentMessage]]],
    get_follow_up_messages: Optional[Callable[[], list[AgentMessage]]],
) -> None:
    """内部循环实现"""
    try:
        event_stream.push(AgentEvent(type=AgentEventType.AGENT_START))

        iteration = 0

        # 外层循环：follow-up 驱动
        while iteration < loop_config.max_iterations:
            if abort_signal and abort_signal():
                break

            iteration += 1
            event_stream.push(AgentEvent(
                type=AgentEventType.TURN_START,
                data={"iteration": iteration},
            ))

            # 调用 LLM
            assistant_msg: AssistantMessage = await stream_fn(
                messages=messages,
                config=llm_config,
                system_prompt=loop_config.system_prompt,
                tools=tools,
                event_stream=event_stream,
            )

            messages.append(assistant_msg)
            tool_calls = assistant_msg.tool_calls

            if not tool_calls:
                # 没有工具调用 — 检查 follow-up
                event_stream.push(AgentEvent(type=AgentEventType.TURN_END))

                if get_follow_up_messages:
                    follow_ups = get_follow_up_messages()
                    if follow_ups:
                        messages.extend(follow_ups)
                        continue
                break

            # 内层循环：执行工具调用
            for tc in tool_calls:
                if abort_signal and abort_signal():
                    break

                # 检查 steering 消息
                if get_steering_messages:
                    steering = get_steering_messages()
                    if steering:
                        messages.extend(steering)
                        break  # 跳过剩余工具，回到 LLM

                await _execute_tool_call(
                    tc=tc,
                    tool_map=tool_map,
                    messages=messages,
                    event_stream=event_stream,
                )

            event_stream.push(AgentEvent(type=AgentEventType.TURN_END))

        else:
            # 达到最大迭代次数
            event_stream.push(AgentEvent(
                type=AgentEventType.ERROR,
                data=f"Reached max iterations ({loop_config.max_iterations})",
            ))

        event_stream.push(AgentEvent(type=AgentEventType.AGENT_END))
        event_stream.set_result(messages)
        event_stream.end()

    except Exception as e:
        logger.error(f"Agent loop error: {e}")
        event_stream.push(AgentEvent(type=AgentEventType.ERROR, data=str(e)))
        event_stream.end(error=e)


async def _execute_tool_call(
    tc: ToolCallContent,
    tool_map: dict[str, AgentTool],
    messages: list[AgentMessage],
    event_stream: EventStream[AgentEvent],
) -> None:
    """执行单个工具调用"""
    event_stream.push(AgentEvent(
        type=AgentEventType.TOOL_START,
        data={"tool_call_id": tc.id, "name": tc.name, "arguments": tc.arguments},
    ))

    tool = tool_map.get(tc.name)
    if not tool:
        result = AgentToolResult(
            content=[TextContent(text=f"Error: Tool '{tc.name}' not found.")],
            is_error=True,
        )
    else:
        try:
            def on_update(data: Any) -> None:
                event_stream.push(AgentEvent(
                    type=AgentEventType.TOOL_UPDATE,
                    data={"tool_call_id": tc.id, "name": tc.name, "update": data},
                ))

            result = await tool.execute(
                tool_call_id=tc.id,
                params=tc.arguments,
                on_update=on_update,
            )
        except Exception as e:
            logger.error(f"Tool '{tc.name}' error: {e}")
            result = AgentToolResult(
                content=[TextContent(text=f"Error executing tool '{tc.name}': {e}")],
                is_error=True,
            )

    # 构建 ToolResultMessage
    tool_result_msg = ToolResultMessage(
        tool_call_id=tc.id,
        tool_name=tc.name,
        content=result.content,
        is_error=result.is_error,
        details=result.details,
    )
    messages.append(tool_result_msg)

    event_stream.push(AgentEvent(
        type=AgentEventType.TOOL_END,
        data={
            "tool_call_id": tc.id,
            "name": tc.name,
            "result": tool_result_msg.text,
            "is_error": result.is_error,
        },
    ))
