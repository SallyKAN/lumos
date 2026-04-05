"""
Lumos Interceptor — Protocol 定义

定义拦截器必须实现的接口。使用 Python Protocol 而非 ABC，
允许鸭子类型（不需要显式继承）。
"""

from __future__ import annotations

from typing import Any, Callable, Awaitable, Protocol, runtime_checkable

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

# proceed 函数签名：调用链中的下一个 interceptor 或 core 函数
ProceedFn = Callable[..., Awaitable[Any]]


@runtime_checkable
class InterceptorProtocol(Protocol):
    """拦截器协议

    10 个生命周期点，全部可选。
    未实现的方法默认透传（由 BaseInterceptor 提供）。

    生命周期点：
    1. before_agent  — agent 启动前
    2. after_agent   — agent 结束后
    3. before_model  — LLM 调用前（可修改 request）
    4. wrap_model    — 包裹 LLM 调用（洋葱模型）
    5. after_model   — LLM 返回后（可修改 response）
    6. pre_tool_use  — 工具执行前（可阻止执行）
    7. wrap_tool     — 包裹工具执行（洋葱模型）
    8. post_tool_use — 工具执行后（可修改结果）
    9. stop          — agent 即将停止（可阻止停止）
    10. error        — 错误发生时（可恢复）
    """

    @property
    def name(self) -> str: ...

    @property
    def priority(self) -> int: ...

    async def before_agent(self, context: AgentContext, proceed: ProceedFn) -> None: ...
    async def after_agent(self, context: AgentContext, proceed: ProceedFn) -> None: ...
    async def before_model(self, request: ModelRequest, proceed: ProceedFn) -> ModelRequest: ...
    async def wrap_model(self, request: ModelRequest, proceed: ProceedFn) -> ModelResponse: ...
    async def after_model(self, response: ModelResponse, proceed: ProceedFn) -> ModelResponse: ...
    async def pre_tool_use(self, request: ToolRequest, proceed: ProceedFn) -> ToolRequest | ToolResult: ...
    async def wrap_tool(self, request: ToolRequest, proceed: ProceedFn) -> ToolResult: ...
    async def post_tool_use(self, result: ToolResult, proceed: ProceedFn) -> ToolResult: ...
    async def stop(self, context: StopContext, proceed: ProceedFn) -> StopDecision: ...
    async def error(self, error: AgentError, proceed: ProceedFn) -> ErrorRecovery: ...
