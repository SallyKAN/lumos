"""
Lumos Interceptor — 拦截器系统

洋葱模型拦截器，10 个生命周期点。
"""

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
from .protocol import InterceptorProtocol
from .base import BaseInterceptor
from .engine import InterceptorEngine

__all__ = [
    # Types
    "AgentContext",
    "ModelRequest",
    "ModelResponse",
    "ToolRequest",
    "ToolResult",
    "StopContext",
    "StopDecision",
    "AgentError",
    "ErrorRecovery",
    # Protocol & Base
    "InterceptorProtocol",
    "BaseInterceptor",
    # Engine
    "InterceptorEngine",
]
