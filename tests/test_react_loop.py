"""
新架构核心测试 — 替代旧的 test_react_loop.py

测试 AgentTool、wrap_legacy_tool、EventStream 等新组件。
"""
import asyncio
import pytest
from packages.server.core.tool import (
    BaseTool, ToolParam, AgentTool, AgentToolResult, wrap_legacy_tool,
)
from packages.server.core.types import (
    TextContent, AgentEvent, AgentEventType, LLMConfig, AgentLoopConfig,
)
from packages.server.core.event_stream import EventStream


# --- Test Tools ---

class GreetTool(BaseTool):
    name = "greet"
    description = "Greet someone"
    params = [ToolParam(name="name", description="Name to greet")]

    async def execute(self, **kwargs) -> str:
        return f"Hello, {kwargs['name']}!"


class FailTool(BaseTool):
    name = "fail"
    description = "Always fails"
    params = []

    async def execute(self, **kwargs) -> str:
        raise RuntimeError("Tool execution failed")


# --- AgentTool Tests ---

def test_agent_tool_creation():
    async def _exec(tool_call_id, params, **kwargs):
        return AgentToolResult(content=[TextContent(text="ok")])

    tool = AgentTool(
        name="test",
        description="A test tool",
        parameters={"type": "object", "properties": {}, "required": []},
        execute_fn=_exec,
    )
    assert tool.name == "test"
    assert tool.label == "test"


@pytest.mark.asyncio
async def test_agent_tool_execute():
    async def _exec(tool_call_id, params, **kwargs):
        return AgentToolResult(content=[TextContent(text=f"got {params['x']}")])

    tool = AgentTool(
        name="echo",
        description="Echo",
        parameters={"type": "object", "properties": {"x": {"type": "string"}}},
        execute_fn=_exec,
    )
    result = await tool.execute(tool_call_id="1", params={"x": "hello"})
    assert not result.is_error
    assert result.content[0].text == "got hello"


def test_agent_tool_to_schema():
    async def _exec(tool_call_id, params, **kwargs):
        return AgentToolResult(content=[])

    tool = AgentTool(
        name="foo",
        description="Foo tool",
        parameters={"type": "object", "properties": {"a": {"type": "string"}}, "required": ["a"]},
        execute_fn=_exec,
    )
    schema = tool.to_schema()
    assert schema["name"] == "foo"
    assert "input_schema" in schema
    assert schema["input_schema"]["properties"]["a"]["type"] == "string"

    openai_schema = tool.to_openai_schema()
    assert openai_schema["type"] == "function"
    assert openai_schema["function"]["name"] == "foo"


# --- wrap_legacy_tool Tests ---

@pytest.mark.asyncio
async def test_wrap_legacy_tool():
    wrapped = wrap_legacy_tool(GreetTool())
    assert wrapped.name == "greet"
    result = await wrapped.execute(tool_call_id="1", params={"name": "World"})
    assert not result.is_error
    assert result.content[0].text == "Hello, World!"


@pytest.mark.asyncio
async def test_wrap_legacy_tool_error():
    wrapped = wrap_legacy_tool(FailTool())
    # FailTool raises RuntimeError, wrap_legacy_tool doesn't catch it
    with pytest.raises(RuntimeError, match="Tool execution failed"):
        await wrapped.execute(tool_call_id="1", params={})


def test_wrap_legacy_tool_schema():
    wrapped = wrap_legacy_tool(GreetTool())
    schema = wrapped.to_anthropic_schema()
    assert schema["name"] == "greet"
    assert "input_schema" in schema
    assert "name" in schema["input_schema"]["properties"]


# --- EventStream Tests ---

@pytest.mark.asyncio
async def test_event_stream_basic():
    stream: EventStream[str] = EventStream()
    stream.push("a")
    stream.push("b")
    stream.end()

    collected = []
    async for item in stream:
        collected.append(item)
    assert collected == ["a", "b"]


@pytest.mark.asyncio
async def test_event_stream_result():
    stream: EventStream[int] = EventStream()
    stream.push(1)
    stream.set_result("done")
    stream.end()

    async for _ in stream:
        pass
    result = await stream.result()
    assert result == "done"


@pytest.mark.asyncio
async def test_event_stream_error():
    stream: EventStream[str] = EventStream()
    stream.end(error=ValueError("bad"))

    with pytest.raises(ValueError, match="bad"):
        async for _ in stream:
            pass

    with pytest.raises(ValueError, match="bad"):
        await stream.result()


# --- LLMConfig in new types ---

def test_llm_config_for_agent():
    config = LLMConfig(provider="anthropic", model="test", api_key="test")
    assert config.provider == "anthropic"
    assert config.max_tokens == 8192


def test_agent_loop_config():
    config = AgentLoopConfig(
        system_prompt="You are helpful.",
        max_iterations=50,
    )
    assert config.system_prompt == "You are helpful."
    assert config.max_iterations == 50
