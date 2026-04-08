"""
Lumos Core — 纯函数 Agent Loop

Pi Agent 风格的双层循环：
- 外层：follow-up 消息驱动继续
- 内层：tool call + steering 消息处理
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Optional, TYPE_CHECKING

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

if TYPE_CHECKING:
    from ..interceptor.engine import InterceptorEngine

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
    interceptor_engine: Optional[InterceptorEngine] = None,
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
        interceptor_engine=interceptor_engine,
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
    interceptor_engine: Optional[InterceptorEngine] = None,
) -> None:
    """内部循环实现"""
    try:
        # 构建 AgentContext（如果有 interceptor_engine）
        _agent_context = None
        if interceptor_engine:
            from ..interceptor.types import AgentContext
            _agent_context = AgentContext(
                messages=messages,
                tools=tools,
                llm_config=llm_config,
                loop_config=loop_config,
            )
            await interceptor_engine.run_before_agent(_agent_context)

        event_stream.push(AgentEvent(type=AgentEventType.AGENT_START))

        iteration = 0

        # 外层循环：follow-up 驱动
        while iteration < loop_config.max_iterations:
            if abort_signal and abort_signal():
                break

            iteration += 1
            if _agent_context:
                _agent_context.iteration = iteration

            event_stream.push(AgentEvent(
                type=AgentEventType.TURN_START,
                data={"iteration": iteration},
            ))

            # === before_model 拦截点 ===
            if interceptor_engine:
                from ..interceptor.types import ModelRequest, ModelResponse
                model_req = ModelRequest(
                    messages=messages,
                    system_prompt=loop_config.system_prompt,
                    tools=tools,
                    llm_config=llm_config,
                )
                model_req = await interceptor_engine.run_before_model(model_req)

                # === wrap_model 拦截点 ===
                async def _core_model(req: ModelRequest) -> ModelResponse:
                    msg = await stream_fn(
                        messages=req.messages,
                        config=req.llm_config,
                        system_prompt=req.system_prompt,
                        tools=req.tools,
                        event_stream=event_stream,
                    )
                    return ModelResponse(message=msg, request=req)

                model_resp = await interceptor_engine.run_wrap_model(model_req, _core_model)

                # === after_model 拦截点 ===
                model_resp = await interceptor_engine.run_after_model(model_resp)
                assistant_msg = model_resp.message
            else:
                # 无 interceptor — 原始路径
                assistant_msg = await stream_fn(
                    messages=messages,
                    config=llm_config,
                    system_prompt=loop_config.system_prompt,
                    tools=tools,
                    event_stream=event_stream,
                )

            messages.append(assistant_msg)
            tool_calls = assistant_msg.tool_calls

            if not tool_calls:
                # 没有工具调用 — 检查 stop 拦截点
                if interceptor_engine:
                    from ..interceptor.types import StopContext
                    stop_ctx = StopContext(reason="no_tool_calls", messages=messages)
                    stop_decision = await interceptor_engine.run_stop(stop_ctx)
                    if not stop_decision.should_stop:
                        if stop_decision.inject_messages:
                            messages.extend(stop_decision.inject_messages)
                        event_stream.push(AgentEvent(type=AgentEventType.TURN_END))
                        continue

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
                    interceptor_engine=interceptor_engine,
                )

            event_stream.push(AgentEvent(type=AgentEventType.TURN_END))

        else:
            # 达到最大迭代次数
            event_stream.push(AgentEvent(
                type=AgentEventType.ERROR,
                data=f"Reached max iterations ({loop_config.max_iterations})",
            ))

        if interceptor_engine and _agent_context:
            await interceptor_engine.run_after_agent(_agent_context)

        event_stream.push(AgentEvent(type=AgentEventType.AGENT_END))
        event_stream.set_result(messages)
        event_stream.end()

    except Exception as e:
        if interceptor_engine:
            from ..interceptor.types import AgentError
            agent_err = AgentError(exception=e, phase="loop", context=_agent_context)
            recovery = await interceptor_engine.run_error(agent_err)
            if recovery.handled:
                if recovery.inject_messages:
                    messages.extend(recovery.inject_messages)
                event_stream.push(AgentEvent(type=AgentEventType.AGENT_END))
                event_stream.set_result(messages)
                event_stream.end()
                return

        logger.error(f"Agent loop error: {e}")
        event_stream.push(AgentEvent(type=AgentEventType.ERROR, data=str(e)))
        event_stream.end(error=e)


async def _execute_tool_call(
    tc: ToolCallContent,
    tool_map: dict[str, AgentTool],
    messages: list[AgentMessage],
    event_stream: EventStream[AgentEvent],
    interceptor_engine: Optional[InterceptorEngine] = None,
) -> None:
    """执行单个工具调用"""
    event_stream.push(AgentEvent(
        type=AgentEventType.TOOL_START,
        data={"tool_call_id": tc.id, "name": tc.name, "arguments": tc.arguments},
    ))

    tool = tool_map.get(tc.name)

    if interceptor_engine:
        from ..interceptor.types import ToolRequest as IToolRequest, ToolResult as IToolResult

        # === pre_tool_use 拦截点 ===
        tool_req = IToolRequest(
            tool_call_id=tc.id,
            tool_name=tc.name,
            arguments=tc.arguments,
            tool=tool,
        )
        pre_result = await interceptor_engine.run_pre_tool_use(tool_req)

        if isinstance(pre_result, IToolResult):
            # 被拦截器阻断
            tool_result_msg = ToolResultMessage(
                tool_call_id=tc.id,
                tool_name=tc.name,
                content=pre_result.content,
                is_error=pre_result.is_error,
                details=pre_result.details,
            )
            messages.append(tool_result_msg)
            event_stream.push(AgentEvent(
                type=AgentEventType.TOOL_END,
                data={"tool_call_id": tc.id, "name": tc.name,
                      "result": tool_result_msg.text, "is_error": pre_result.is_error},
            ))
            return

        # pre_result is ToolRequest (possibly modified)
        tool_req = pre_result

        # === wrap_tool 拦截点 ===
        async def _core_tool(req: IToolRequest) -> IToolResult:
            t = req.tool or tool_map.get(req.tool_name)
            if not t:
                return IToolResult(
                    tool_call_id=req.tool_call_id,
                    tool_name=req.tool_name,
                    content=[TextContent(text=f"Error: Tool '{req.tool_name}' not found.")],
                    is_error=True,
                    request=req,
                )
            try:
                def on_update(data: Any) -> None:
                    event_stream.push(AgentEvent(
                        type=AgentEventType.TOOL_UPDATE,
                        data={"tool_call_id": req.tool_call_id, "name": req.tool_name, "update": data},
                    ))
                r = await t.execute(
                    tool_call_id=req.tool_call_id,
                    params=req.arguments,
                    on_update=on_update,
                )
                return IToolResult(
                    tool_call_id=req.tool_call_id,
                    tool_name=req.tool_name,
                    content=r.content,
                    is_error=r.is_error,
                    details=r.details,
                    request=req,
                )
            except Exception as e:
                logger.error(f"Tool '{req.tool_name}' error: {e}")
                return IToolResult(
                    tool_call_id=req.tool_call_id,
                    tool_name=req.tool_name,
                    content=[TextContent(text=f"Error executing tool '{req.tool_name}': {e}")],
                    is_error=True,
                    request=req,
                )

        i_result = await interceptor_engine.run_wrap_tool(tool_req, _core_tool)

        # === post_tool_use 拦截点 ===
        i_result = await interceptor_engine.run_post_tool_use(i_result)

        tool_result_msg = ToolResultMessage(
            tool_call_id=tc.id,
            tool_name=tc.name,
            content=i_result.content,
            is_error=i_result.is_error,
            details=i_result.details,
        )
    else:
        # 无 interceptor — 原始路径
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
            "is_error": tool_result_msg.is_error,
        },
    ))
