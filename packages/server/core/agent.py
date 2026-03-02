"""
Lumos Core — 有状态 Agent 类

管理 state / abort / queues / 事件订阅。
包装纯函数 agent_loop，提供面向对象的接口。
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from .agent_loop import agent_loop
from .event_stream import EventStream
from .stream_fn import StreamFn
from .tool import AgentTool
from .types import (
    AgentEvent,
    AgentEventType,
    AgentLoopConfig,
    AgentMessage,
    LLMConfig,
    UserMessage,
)

logger = logging.getLogger(__name__)


@dataclass
class AgentState:
    """Agent 内部状态"""
    system_prompt: str = ""
    model: str = ""
    tools: list[AgentTool] = field(default_factory=list)
    messages: list[AgentMessage] = field(default_factory=list)
    is_running: bool = False
    error: Optional[str] = None


class Agent:
    """有状态 Agent

    用法:
        agent = Agent(llm_config=config, loop_config=loop_config)
        agent.set_system_prompt("You are helpful.")
        agent.set_tools([tool1, tool2])

        agent.subscribe(my_handler)
        await agent.prompt("Hello")
    """

    def __init__(
        self,
        llm_config: LLMConfig,
        loop_config: Optional[AgentLoopConfig] = None,
        stream_fn: Optional[StreamFn] = None,
    ):
        self._llm_config = llm_config
        self._loop_config = loop_config or AgentLoopConfig()
        self._stream_fn = stream_fn
        self._state = AgentState(model=llm_config.model)
        self._subscribers: list[Callable[[AgentEvent], Any]] = []
        self._abort = False
        self._steering_queue: list[AgentMessage] = []
        self._follow_up_queue: list[AgentMessage] = []
        self._current_stream: Optional[EventStream[AgentEvent]] = None
        self._run_task: Optional[asyncio.Task] = None

    # ==================== 配置 ====================

    def set_system_prompt(self, prompt: str) -> None:
        self._state.system_prompt = prompt
        self._loop_config.system_prompt = prompt

    def set_tools(self, tools: list[AgentTool]) -> None:
        self._state.tools = list(tools)

    def set_model(self, model: str) -> None:
        self._state.model = model
        self._llm_config.model = model

    # ==================== 事件订阅 ====================

    def subscribe(self, fn: Callable[[AgentEvent], Any]) -> Callable[[], None]:
        """订阅事件，返回取消订阅函数"""
        self._subscribers.append(fn)

        def unsubscribe() -> None:
            if fn in self._subscribers:
                self._subscribers.remove(fn)

        return unsubscribe

    def _emit(self, event: AgentEvent) -> None:
        """发送事件给所有订阅者"""
        for fn in self._subscribers:
            try:
                fn(event)
            except Exception as e:
                logger.error(f"Subscriber error: {e}")

    # ==================== 执行 ====================

    async def prompt(self, input_: str | AgentMessage) -> None:
        """发送消息并运行 agent loop"""
        if self._state.is_running:
            logger.warning("Agent is already running, ignoring prompt")
            return

        # 构建用户消息
        if isinstance(input_, str):
            msg = UserMessage(content=input_)
        else:
            msg = input_
        self._state.messages.append(msg)

        await self._run()

    async def continue_(self) -> None:
        """继续运行（不添加新消息）"""
        if self._state.is_running:
            return
        await self._run()

    async def _run(self) -> None:
        """内部运行逻辑"""
        self._state.is_running = True
        self._state.error = None
        self._abort = False

        try:
            stream = await agent_loop(
                messages=self._state.messages,
                tools=self._state.tools,
                llm_config=self._llm_config,
                loop_config=self._loop_config,
                stream_fn=self._stream_fn,
                abort_signal=lambda: self._abort,
                get_steering_messages=self._drain_steering,
                get_follow_up_messages=self._drain_follow_up,
            )
            self._current_stream = stream

            # 消费事件流
            async for event in stream:
                self._emit(event)

        except Exception as e:
            self._state.error = str(e)
            self._emit(AgentEvent(type=AgentEventType.ERROR, data=str(e)))
        finally:
            self._state.is_running = False
            self._current_stream = None

    # ==================== 控制 ====================

    def abort(self) -> None:
        """中止当前运行"""
        self._abort = True
        if self._current_stream and not self._current_stream.ended:
            self._current_stream.end()

    def reset(self) -> None:
        """重置 agent 状态"""
        self.abort()
        self._state.messages.clear()
        self._state.error = None
        self._steering_queue.clear()
        self._follow_up_queue.clear()

    # ==================== Steering ====================

    def steer(self, msg: str | AgentMessage) -> None:
        """添加 steering 消息（中断当前工具执行）"""
        if isinstance(msg, str):
            msg = UserMessage(content=msg)
        self._steering_queue.append(msg)

    def follow_up(self, msg: str | AgentMessage) -> None:
        """添加 follow-up 消息（agent 停止前检查）"""
        if isinstance(msg, str):
            msg = UserMessage(content=msg)
        self._follow_up_queue.append(msg)

    def clear_all_queues(self) -> None:
        """清空所有队列"""
        self._steering_queue.clear()
        self._follow_up_queue.clear()

    def _drain_steering(self) -> list[AgentMessage]:
        """取出并清空 steering 队列"""
        if not self._steering_queue:
            return []
        msgs = list(self._steering_queue)
        self._steering_queue.clear()
        return msgs

    def _drain_follow_up(self) -> list[AgentMessage]:
        """取出并清空 follow-up 队列"""
        if not self._follow_up_queue:
            return []
        msgs = list(self._follow_up_queue)
        self._follow_up_queue.clear()
        return msgs

    # ==================== 状态查询 ====================

    @property
    def is_running(self) -> bool:
        return self._state.is_running

    @property
    def messages(self) -> list[AgentMessage]:
        return self._state.messages

    @property
    def state(self) -> AgentState:
        return self._state
