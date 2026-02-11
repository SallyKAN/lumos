import pytest
from packages.server.core.tool import BaseTool, ToolParam


class EchoTool(BaseTool):
    name = "echo"
    description = "Echo input back"
    params = [
        ToolParam(name="message", description="Message to echo", param_type="string", required=True),
        ToolParam(name="loud", description="Uppercase", param_type="boolean", required=False, default_value=False),
    ]

    async def execute(self, **kwargs) -> str:
        msg = kwargs["message"]
        if kwargs.get("loud"):
            msg = msg.upper()
        return msg


@pytest.mark.asyncio
async def test_tool_basic():
    tool = EchoTool()
    assert tool.name == "echo"
    result = await tool.execute(message="hello")
    assert result == "hello"


@pytest.mark.asyncio
async def test_tool_with_optional_param():
    tool = EchoTool()
    result = await tool.execute(message="hello", loud=True)
    assert result == "HELLO"


def test_tool_to_openai_schema():
    tool = EchoTool()
    schema = tool.to_openai_schema()
    assert schema["type"] == "function"
    assert schema["function"]["name"] == "echo"
    props = schema["function"]["parameters"]["properties"]
    assert "message" in props
    assert "loud" in props
    assert props["loud"]["default"] is False
    assert "message" in schema["function"]["parameters"]["required"]
    assert "loud" not in schema["function"]["parameters"]["required"]


def test_tool_to_anthropic_schema():
    tool = EchoTool()
    schema = tool.to_anthropic_schema()
    assert schema["name"] == "echo"
    assert schema["description"] == "Echo input back"
    assert "input_schema" in schema
    assert "message" in schema["input_schema"]["properties"]


def test_tool_param_with_enum():
    param = ToolParam(name="color", description="Color", enum=["red", "blue"])
    tool = type("T", (BaseTool,), {
        "name": "t", "description": "t",
        "params": [param],
        "execute": lambda self, **kw: "ok",
    })()
    schema = tool.to_openai_schema()
    assert schema["function"]["parameters"]["properties"]["color"]["enum"] == ["red", "blue"]
