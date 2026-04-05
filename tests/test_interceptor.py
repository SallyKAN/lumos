"""T1.1 + T1.2 + T1.3 测试：InterceptorTypes + Engine + BaseInterceptor"""

import pytest
from dataclasses import replace

from packages.server.core.types import (
    UserMessage,
    AssistantMessage,
    TextContent,
    ToolCallContent,
    LLMConfig,
    AgentLoopConfig,
)
from packages.server.core.tool import AgentTool, AgentToolResult
from packages.server.interceptor.types import (
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
from packages.server.interceptor.base import BaseInterceptor
from packages.server.interceptor.engine import InterceptorEngine


# ============================================================================
# Fixtures
# ============================================================================

def _make_llm_config() -> LLMConfig:
    return LLMConfig(provider="anthropic", model="test", api_key="fake")


def _make_loop_config() -> AgentLoopConfig:
    return AgentLoopConfig(system_prompt="test prompt")


def _make_context() -> AgentContext:
    return AgentContext(
        messages=[UserMessage(content="hello")],
        tools=[],
        llm_config=_make_llm_config(),
        loop_config=_make_loop_config(),
    )


def _make_model_request() -> ModelRequest:
    return ModelRequest(
        messages=[UserMessage(content="hello")],
        system_prompt="test",
        tools=[],
        llm_config=_make_llm_config(),
    )


# ============================================================================
# T1.1: InterceptorTypes 测试
# ============================================================================

class TestInterceptorTypes:
    def test_agent_context_creation(self):
        ctx = _make_context()
        assert ctx.iteration == 0
        assert ctx.metadata == {}
        assert len(ctx.messages) == 1

    def test_model_request_with_overrides(self):
        req = _make_model_request()
        new_req = req.with_overrides(system_prompt="modified")
        assert new_req.system_prompt == "modified"
        assert req.system_prompt == "test"  # 原对象不变
        assert new_req is not req

    def test_model_request_with_overrides_preserves_other_fields(self):
        req = _make_model_request()
        new_req = req.with_overrides(system_prompt="modified")
        assert new_req.llm_config is req.llm_config
        assert new_req.messages is req.messages

    def test_stop_decision_defaults(self):
        sd = StopDecision()
        assert sd.should_stop is True
        assert sd.inject_messages == []
        assert sd.reason == ""

    def test_error_recovery_defaults(self):
        er = ErrorRecovery()
        assert er.handled is False
        assert er.retry is False
        assert er.inject_messages == []

    def test_tool_request_creation(self):
        tr = ToolRequest(tool_call_id="tc1", tool_name="read_file", arguments={"path": "/tmp"})
        assert tr.tool_call_id == "tc1"
        assert tr.metadata == {}

    def test_tool_result_creation(self):
        tr = ToolResult(
            tool_call_id="tc1",
            tool_name="read_file",
            content=[TextContent(text="file content")],
        )
        assert tr.is_error is False
        assert tr.content[0].text == "file content"

    def test_agent_error_creation(self):
        err = AgentError(exception=ValueError("boom"), phase="model")
        assert err.phase == "model"
        assert str(err.exception) == "boom"


# ============================================================================
# T1.3: BaseInterceptor 测试
# ============================================================================

class TestBaseInterceptor:
    def test_default_name_and_priority(self):
        i = BaseInterceptor()
        assert i.name == "unnamed"
        assert i.priority == 50

    def test_repr(self):
        i = BaseInterceptor()
        i.name = "test"
        i.priority = 10
        assert "test" in repr(i)
        assert "10" in repr(i)

    @pytest.mark.asyncio
    async def test_default_before_model_passthrough(self):
        i = BaseInterceptor()
        req = _make_model_request()
        called = False

        async def proceed(r):
            nonlocal called
            called = True
            return r

        result = await i.before_model(req, proceed)
        assert called
        assert result is req

    @pytest.mark.asyncio
    async def test_default_stop_passthrough(self):
        i = BaseInterceptor()
        ctx = StopContext(reason="no_tool_calls")

        async def proceed(c):
            return StopDecision(should_stop=True, reason=c.reason)

        decision = await i.stop(ctx, proceed)
        assert decision.should_stop is True


# ============================================================================
# T1.2: InterceptorEngine 测试
# ============================================================================

class LogInterceptor(BaseInterceptor):
    """测试用：记录调用顺序"""
    def __init__(self, name: str, priority: int, log: list):
        self.name = name
        self.priority = priority
        self._log = log

    async def before_model(self, request, proceed):
        self._log.append(f"{self.name}:enter")
        result = await proceed(request)
        self._log.append(f"{self.name}:exit")
        return result


class BlockInterceptor(BaseInterceptor):
    """测试用：阻断 pre_tool_use"""
    name = "blocker"
    priority = 10

    async def pre_tool_use(self, request, proceed):
        return ToolResult(
            tool_call_id=request.tool_call_id,
            tool_name=request.tool_name,
            content=[TextContent(text="blocked")],
            is_error=True,
        )


class TransformInterceptor(BaseInterceptor):
    """测试用：修改 model request"""
    name = "transformer"
    priority = 10

    async def before_model(self, request, proceed):
        new_req = request.with_overrides(system_prompt="transformed")
        return await proceed(new_req)


class TestInterceptorEngine:
    def test_register_and_sort(self):
        engine = InterceptorEngine()
        log = []
        engine.register(LogInterceptor("b", 50, log))
        engine.register(LogInterceptor("a", 10, log))
        engine.register(LogInterceptor("c", 90, log))
        names = [i.name for i in engine.interceptors]
        assert names == ["a", "b", "c"]

    def test_unregister(self):
        engine = InterceptorEngine()
        engine.register(LogInterceptor("a", 10, []))
        engine.register(LogInterceptor("b", 50, []))
        assert engine.unregister("a") is True
        assert len(engine.interceptors) == 1
        assert engine.unregister("nonexistent") is False

    @pytest.mark.asyncio
    async def test_onion_order(self):
        """E2E-P1-01: 洋葱模型执行顺序"""
        engine = InterceptorEngine()
        log = []
        engine.register(LogInterceptor("p50", 50, log))
        engine.register(LogInterceptor("p10", 10, log))
        engine.register(LogInterceptor("p90", 90, log))

        req = _make_model_request()
        await engine.run_before_model(req)

        assert log == [
            "p10:enter", "p50:enter", "p90:enter",
            "p90:exit", "p50:exit", "p10:exit",
        ]

    @pytest.mark.asyncio
    async def test_interceptor_block(self):
        """E2E-P1-02: 拦截器阻断"""
        engine = InterceptorEngine()
        engine.register(BlockInterceptor())

        inner_called = False
        inner_interceptor = BaseInterceptor()
        inner_interceptor.name = "inner"
        inner_interceptor.priority = 50

        original_pre = inner_interceptor.pre_tool_use
        async def tracking_pre(request, proceed):
            nonlocal inner_called
            inner_called = True
            return await original_pre(request, proceed)
        inner_interceptor.pre_tool_use = tracking_pre
        engine.register(inner_interceptor)

        req = ToolRequest(tool_call_id="tc1", tool_name="test", arguments={})
        result = await engine.run_pre_tool_use(req)

        assert isinstance(result, ToolResult)
        assert result.is_error is True
        assert inner_called is False

    @pytest.mark.asyncio
    async def test_interceptor_transform(self):
        """E2E-P1-03: 拦截器变换"""
        engine = InterceptorEngine()
        engine.register(TransformInterceptor())

        req = _make_model_request()
        result = await engine.run_before_model(req)

        assert result.system_prompt == "transformed"

    @pytest.mark.asyncio
    async def test_empty_engine_passthrough(self):
        """无 interceptor 时透传"""
        engine = InterceptorEngine()
        req = _make_model_request()
        result = await engine.run_before_model(req)
        assert result is req

    @pytest.mark.asyncio
    async def test_stop_default(self):
        engine = InterceptorEngine()
        ctx = StopContext(reason="no_tool_calls")
        decision = await engine.run_stop(ctx)
        assert decision.should_stop is True
        assert decision.reason == "no_tool_calls"

    @pytest.mark.asyncio
    async def test_error_default(self):
        engine = InterceptorEngine()
        err = AgentError(exception=ValueError("boom"), phase="model")
        recovery = await engine.run_error(err)
        assert recovery.handled is False

    @pytest.mark.asyncio
    async def test_wrap_model(self):
        """wrap_model 包裹实际 LLM 调用"""
        engine = InterceptorEngine()

        async def core_model(request):
            return ModelResponse(
                message=AssistantMessage(content=[TextContent(text="hello")]),
                request=request,
            )

        req = _make_model_request()
        resp = await engine.run_wrap_model(req, core_model)
        assert resp.message.text == "hello"

    @pytest.mark.asyncio
    async def test_wrap_tool(self):
        """wrap_tool 包裹实际工具执行"""
        engine = InterceptorEngine()

        async def core_tool(request):
            return ToolResult(
                tool_call_id=request.tool_call_id,
                tool_name=request.tool_name,
                content=[TextContent(text="result")],
            )

        req = ToolRequest(tool_call_id="tc1", tool_name="test", arguments={})
        result = await engine.run_wrap_tool(req, core_tool)
        assert result.content[0].text == "result"
