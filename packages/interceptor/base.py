"""
Lumos Interceptor — 便利基类

所有生命周期方法默认透传（调用 proceed）。
子类只需覆盖关心的方法。
"""

from __future__ import annotations

from typing import Union

from .types import (
    AgentContext,
    ModelRequest,
    ModelResponse,
    ToolRequest,
    ToolResult,
    StopContext,
    StopDecision,
    AgentError,
    ErrorRecovery,
)
from .protocol import ProceedFn


class BaseInterceptor:
    """拦截器便利基类

    所有方法默认调用 proceed() 透传。子类只需覆盖关心的生命周期点。

    Example:
        class MyInterceptor(BaseInterceptor):
            name = "my-interceptor"
            priority = 50

            async def before_model(self, request, proceed):
                # 修改 request
                request = request.with_overrides(system_prompt="custom")
                return await proceed(request)
    """

    name: str = "unnamed"
    priority: int = 50  # 0=最外层, 100=最内层

    async def before_agent(self, context: AgentContext, proceed: ProceedFn) -> None:
        return await proceed(context)

    async def after_agent(self, context: AgentContext, proceed: ProceedFn) -> None:
        return await proceed(context)

    async def before_model(self, request: ModelRequest, proceed: ProceedFn) -> ModelRequest:
        return await proceed(request)

    async def wrap_model(self, request: ModelRequest, proceed: ProceedFn) -> ModelResponse:
        return await proceed(request)

    async def after_model(self, response: ModelResponse, proceed: ProceedFn) -> ModelResponse:
        return await proceed(response)

    async def pre_tool_use(self, request: ToolRequest, proceed: ProceedFn) -> Union[ToolRequest, ToolResult]:
        return await proceed(request)

    async def wrap_tool(self, request: ToolRequest, proceed: ProceedFn) -> ToolResult:
        return await proceed(request)

    async def post_tool_use(self, result: ToolResult, proceed: ProceedFn) -> ToolResult:
        return await proceed(result)

    async def stop(self, context: StopContext, proceed: ProceedFn) -> StopDecision:
        return await proceed(context)

    async def error(self, error: AgentError, proceed: ProceedFn) -> ErrorRecovery:
        return await proceed(error)

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__} name={self.name!r} priority={self.priority}>"
