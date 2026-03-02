"""
Core Types 测试 — 替代旧的 test_core_llm.py

测试新的 types.py 中的 LLMConfig、消息类型、内容块等。
"""
import pytest
from packages.server.core.types import (
    LLMConfig,
    UserMessage,
    AssistantMessage,
    ToolResultMessage,
    TextContent,
    ThinkingContent,
    ToolCallContent,
    AgentEvent,
    AgentEventType,
    AgentLoopConfig,
)


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


def test_llm_config_defaults():
    config = LLMConfig(provider="openai", model="gpt-4o", api_key="k")
    assert config.api_base is None
    assert config.timeout == 120
    assert config.top_p is None


def test_user_message():
    msg = UserMessage(content="hello")
    assert msg.role == "user"
    assert msg.content == "hello"
    assert msg.timestamp > 0


def test_assistant_message_text():
    msg = AssistantMessage(content=[TextContent(text="hi")])
    assert msg.role == "assistant"
    assert msg.text == "hi"
    assert msg.tool_calls == []


def test_assistant_message_tool_calls():
    tc = ToolCallContent(id="1", name="read_file", arguments={"path": "/tmp"})
    msg = AssistantMessage(content=[TextContent(text="ok"), tc])
    assert msg.text == "ok"
    assert len(msg.tool_calls) == 1
    assert msg.tool_calls[0].name == "read_file"


def test_tool_result_message():
    msg = ToolResultMessage(
        tool_call_id="1",
        tool_name="read_file",
        content=[TextContent(text="file content")],
    )
    assert msg.role == "tool_result"
    assert msg.text == "file content"
    assert msg.is_error is False


def test_tool_call_content():
    tc = ToolCallContent(id="abc", name="bash", arguments={"command": "ls"})
    assert tc.id == "abc"
    assert tc.name == "bash"
    assert tc.arguments == {"command": "ls"}
    assert tc.type == "tool_call"


def test_thinking_content():
    t = ThinkingContent(thinking="let me think...")
    assert t.type == "thinking"
    assert t.thinking == "let me think..."


def test_agent_event():
    event = AgentEvent(type=AgentEventType.MESSAGE_DELTA, data={"text": "hi"})
    assert event.type == AgentEventType.MESSAGE_DELTA
    assert event.data == {"text": "hi"}


def test_agent_loop_config_defaults():
    config = AgentLoopConfig()
    assert config.system_prompt == ""
    assert config.max_iterations == 100
