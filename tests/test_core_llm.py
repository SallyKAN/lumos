import pytest
from packages.server.core.llm import LLMConfig, Message, ToolCall


def test_llm_config():
    config = LLMConfig(
        provider="anthropic",
        model="claude-sonnet-4-20250514",
        api_key="test-key",
    )
    assert config.provider == "anthropic"
    assert config.model == "claude-sonnet-4-20250514"
    assert config.temperature == 0.0
    assert config.max_tokens == 8192


def test_message_creation():
    msg = Message(role="user", content="hello")
    assert msg.role == "user"
    d = msg.to_dict()
    assert d == {"role": "user", "content": "hello"}


def test_message_factory_methods():
    assert Message.user("hi").role == "user"
    assert Message.assistant("ok").role == "assistant"
    assert Message.system("sys").role == "system"

    tool_msg = Message.tool_result("call_1", "result", "read_file")
    assert tool_msg.role == "tool"
    assert tool_msg.tool_call_id == "call_1"
    assert tool_msg.name == "read_file"


def test_message_with_tool_calls():
    tc = ToolCall(id="1", name="read_file", arguments={"path": "/tmp/test"})
    msg = Message.assistant("", tool_calls=[tc])
    d = msg.to_dict()
    assert len(d["tool_calls"]) == 1
    assert d["tool_calls"][0]["name"] == "read_file"


def test_tool_call_dataclass():
    tc = ToolCall(id="abc", name="bash", arguments={"command": "ls"})
    assert tc.id == "abc"
    assert tc.name == "bash"
    assert tc.arguments == {"command": "ls"}
