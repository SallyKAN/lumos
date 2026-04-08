"""
Lumos Core — EventStream

基于 asyncio.Queue 的异步事件流。
生产者 push 事件，消费者 async for 迭代。
"""

from __future__ import annotations

import asyncio
from typing import Any, Generic, Optional, TypeVar

T = TypeVar("T")

_SENTINEL = object()


class EventStream(Generic[T]):
    """异步事件流

    用法:
        stream = EventStream()

        # 生产者
        stream.push(event1)
        stream.push(event2)
        stream.end()

        # 消费者
        async for event in stream:
            handle(event)

        result = await stream.result()
    """

    def __init__(self) -> None:
        self._queue: asyncio.Queue = asyncio.Queue()
        self._ended = False
        self._error: Optional[Exception] = None
        self._result_value: Any = None
        self._result_set = False
        self._result_event = asyncio.Event()

    def push(self, event: T) -> None:
        """推送事件到流"""
        if self._ended:
            return
        self._queue.put_nowait(event)

    def end(self, error: Optional[Exception] = None) -> None:
        """结束流"""
        if self._ended:
            return
        self._ended = True
        self._error = error
        self._queue.put_nowait(_SENTINEL)
        if not self._result_set:
            self._result_set = True
            self._result_value = error
            self._result_event.set()

    def set_result(self, result: Any) -> None:
        """设置最终结果"""
        self._result_value = result
        self._result_set = True
        self._result_event.set()

    async def result(self) -> Any:
        """等待并获取最终结果"""
        await self._result_event.wait()
        if isinstance(self._result_value, Exception):
            raise self._result_value
        return self._result_value

    @property
    def ended(self) -> bool:
        return self._ended

    @property
    def error(self) -> Optional[Exception]:
        return self._error

    def __aiter__(self):
        return self

    async def __anext__(self) -> T:
        item = await self._queue.get()
        if item is _SENTINEL:
            if self._error:
                raise self._error
            raise StopAsyncIteration
        return item
