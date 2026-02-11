"""
ReAct Loop 核心测试
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from packages.server.core.react_loop import ReActLoop, ReActEvent, EventType
from packages.server.core.tool import BaseTool, ToolParam
from packages.server.core.llm import LLMConfig, Message, ToolCall


# --- Test Tools ---

class GreetTool(BaseTool):
    name = "greet"
    description = "Greet someone"
    params = [ToolParam(name="name", description="Name to greet")]

    async def execute(self, **kwargs) -> str:
        return f"Hello, {kwargs['name']}!"


class AddTool(BaseTool):
    name = "add"
    description = "Add two numbers"
    params = [
        ToolParam(name="a", description="First number", param_type="number"),
        ToolParam(name="b", description="Second number", param_type="number"),
    ]

    async def execute(self, **kwargs) -> str:
        return str(float(kwargs["a"]) + float(kwargs["b"]))


class FailTool(BaseTool):
    name = "fail"
    description = "Always fails"
    params = []

    async def execute(self, **kwargs) -> str:
        raise RuntimeError("Tool execution failed")


# --- Tests ---

def test_register_tools():
    config = LLMConfig(provider="anthropic", model="test", api_key="test")
    loop = ReActLoop(config=config)
    loop.add_tool(GreetTool())
    loop.add_tool(AddTool())
    assert "greet" in loop.tools
    assert "add" in loop.tools
    assert len(loop.tools) == 2


@pytest.mark.asyncio
async def test_execute_tool():
    config = LLMConfig(provider="anthropic", model="test", api_key="test")
    loop = ReActLoop(config=config)
    loop.add_tool(GreetTool())
    result = await loop.execute_tool("greet", {"name": "World"})
    assert result == "Hello, World!"


@pytest.mark.asyncio
async def test_execute_tool_not_found():
    config = LLMConfig(provider="anthropic", model="test", api_key="test")
    loop = ReActLoop(config=config)
    result = await loop.execute_tool("nonexistent", {})
    assert "not found" in result.lower() or "未找到" in result.lower() or "error" in result.lower()


@pytest.mark.asyncio
async def test_execute_tool_error_handling():
    config = LLMConfig(provider="anthropic", model="test", api_key="test")
    loop = ReActLoop(config=config)
    loop.add_tool(FailTool())
    result = await loop.execute_tool("fail", {})
    assert "error" in result.lower() or "失败" in result.lower()


def test_get_tool_schemas_anthropic():
    config = LLMConfig(provider="anthropic", model="test", api_key="test")
    loop = ReActLoop(config=config)
    loop.add_tool(GreetTool())
    schemas = loop.get_tool_schemas()
    assert len(schemas) == 1
    assert schemas[0]["name"] == "greet"
    assert "input_schema" in schemas[0]


def test_get_tool_schemas_openai():
    config = LLMConfig(provider="openai", model="test", api_key="test")
    loop = ReActLoop(config=config)
    loop.add_tool(GreetTool())
    schemas = loop.get_tool_schemas()
    assert len(schemas) == 1
    assert schemas[0]["type"] == "function"


def test_max_iterations_default():
    config = LLMConfig(provider="anthropic", model="test", api_key="test")
    loop = ReActLoop(config=config)
    assert loop.max_iterations == 25


def test_react_event():
    event = ReActEvent(type=EventType.TEXT, content="hello")
    assert event.type == EventType.TEXT
    assert event.content == "hello"


def test_build_messages():
    config = LLMConfig(provider="anthropic", model="test", api_key="test")
    loop = ReActLoop(config=config, system_prompt="You are helpful.")
    messages = loop._build_messages("Hello")
    # For anthropic, system prompt is separate, messages start with user
    assert any(m.role == "user" and m.content == "Hello" for m in messages)
