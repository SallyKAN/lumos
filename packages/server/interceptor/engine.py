"""
Lumos Interceptor — 洋葱模型执行引擎

按 priority 排序拦截器，对每个生命周期点构建 proceed 调用链。
priority 数字越小越在外层（越先执行、越后返回）。
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Awaitable, Optional, Union

from .base import BaseInterceptor
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

logger = logging.getLogger(__name__)

# 核心函数签名：洋葱最内层的实际执行函数
CoreFn = Callable[..., Awaitable[Any]]


class InterceptorEngine:
    """拦截器执行引擎

    职责：
    1. 管理已注册的 interceptor 列表
    2. 按 priority 排序
    3. 对每个生命周期点构建洋葱调用链
    4. 执行调用链

    用法:
        engine = InterceptorEngine()
        engine.register(MyInterceptor())
        engine.register(AnotherInterceptor())

        # 触发生命周期点
        modified_request = await engine.run_before_model(request)
        response = await engine.run_wrap_model(request, core_model_fn)
    """

    def __init__(self) -> None:
        self._interceptors: list[BaseInterceptor] = []
        self._sorted = True

    def register(self, interceptor: BaseInterceptor) -> None:
        """注册一个拦截器"""
        self._interceptors.append(interceptor)
        self._sorted = False
        logger.debug(f"Registered interceptor: {interceptor}")

    def unregister(self, name: str) -> bool:
        """按名称移除拦截器，返回是否找到"""
        before = len(self._interceptors)
        self._interceptors = [i for i in self._interceptors if i.name != name]
        return len(self._interceptors) < before

    @property
    def interceptors(self) -> list[BaseInterceptor]:
        """返回按 priority 排序的拦截器列表"""
        if not self._sorted:
            self._interceptors.sort(key=lambda i: i.priority)
            self._sorted = True
        return list(self._interceptors)

    def _build_chain(
        self,
        method_name: str,
        core_fn: CoreFn,
    ) -> CoreFn:
        """构建洋葱调用链

        从最内层（priority 最大）到最外层（priority 最小）包裹。
        每个 interceptor 的 method 接收 (data, proceed)，
        proceed 指向下一层。
        """
        chain = core_fn
        # 从内到外包裹：reversed 让 priority 最小的在最外层
        for interceptor in reversed(self.interceptors):
            method = getattr(interceptor, method_name, None)
            if method is None:
                continue
            # 闭包捕获当前 method 和 chain
            chain = self._wrap(method, chain)
        return chain

    @staticmethod
    def _wrap(method: Callable, next_fn: CoreFn) -> CoreFn:
        """包裹单个 interceptor 方法"""
        async def wrapped(data: Any) -> Any:
            return await method(data, next_fn)
        return wrapped

    # ================================================================
    # 公共 API — 每个生命周期点
    # ================================================================

    async def run_before_agent(self, context: AgentContext) -> None:
        """触发 before_agent 链"""
        async def core(ctx: AgentContext) -> None:
            pass  # 无核心操作，纯通知
        chain = self._build_chain("before_agent", core)
        await chain(context)

    async def run_after_agent(self, context: AgentContext) -> None:
        """触发 after_agent 链"""
        async def core(ctx: AgentContext) -> None:
            pass
        chain = self._build_chain("after_agent", core)
        await chain(context)

    async def run_before_model(self, request: ModelRequest) -> ModelRequest:
        """触发 before_model 链，返回可能被修改的 request"""
        async def core(req: ModelRequest) -> ModelRequest:
            return req  # 透传
        chain = self._build_chain("before_model", core)
        return await chain(request)

    async def run_wrap_model(
        self,
        request: ModelRequest,
        core_model_fn: CoreFn,
    ) -> ModelResponse:
        """触发 wrap_model 链，包裹实际的 LLM 调用"""
        chain = self._build_chain("wrap_model", core_model_fn)
        return await chain(request)

    async def run_after_model(self, response: ModelResponse) -> ModelResponse:
        """触发 after_model 链，返回可能被修改的 response"""
        async def core(resp: ModelResponse) -> ModelResponse:
            return resp
        chain = self._build_chain("after_model", core)
        return await chain(response)

    async def run_pre_tool_use(
        self, request: ToolRequest,
    ) -> Union[ToolRequest, ToolResult]:
        """触发 pre_tool_use 链

        返回 ToolRequest 表示继续执行，返回 ToolResult 表示阻断。
        """
        async def core(req: ToolRequest) -> ToolRequest:
            return req
        chain = self._build_chain("pre_tool_use", core)
        return await chain(request)

    async def run_wrap_tool(
        self,
        request: ToolRequest,
        core_tool_fn: CoreFn,
    ) -> ToolResult:
        """触发 wrap_tool 链，包裹实际的工具执行"""
        chain = self._build_chain("wrap_tool", core_tool_fn)
        return await chain(request)

    async def run_post_tool_use(self, result: ToolResult) -> ToolResult:
        """触发 post_tool_use 链，返回可能被修改的 result"""
        async def core(res: ToolResult) -> ToolResult:
            return res
        chain = self._build_chain("post_tool_use", core)
        return await chain(result)

    async def run_stop(self, context: StopContext) -> StopDecision:
        """触发 stop 链，返回是否应该停止"""
        async def core(ctx: StopContext) -> StopDecision:
            return StopDecision(should_stop=True, reason=ctx.reason)
        chain = self._build_chain("stop", core)
        return await chain(context)

    async def run_error(self, error: AgentError) -> ErrorRecovery:
        """触发 error 链，返回恢复策略"""
        async def core(err: AgentError) -> ErrorRecovery:
            return ErrorRecovery(handled=False)
        chain = self._build_chain("error", core)
        return await chain(error)
