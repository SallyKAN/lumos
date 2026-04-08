"""T1.6 + T1.7 测试：TrajectoryLogger + TrajectoryReplay"""

import json
import pytest
from pathlib import Path

from packages.core.types import (
    UserMessage,
    AssistantMessage,
    TextContent,
    ToolCallContent,
    LLMConfig,
    AgentLoopConfig,
)
from packages.interceptor.engine import InterceptorEngine
from packages.interceptor.types import (
    AgentContext,
    ModelRequest,
    ModelResponse,
    ToolRequest,
    ToolResult,
    StopContext,
    AgentError,
)
from packages.optimization.trajectory.logger import TrajectoryLogger
from packages.optimization.trajectory.replay import TrajectoryReplay


def _make_llm_config():
    return LLMConfig(provider="anthropic", model="test-model", api_key="fake")


def _make_context():
    return AgentContext(
        messages=[UserMessage(content="hello")],
        tools=[],
        llm_config=_make_llm_config(),
        loop_config=AgentLoopConfig(system_prompt="test"),
    )


# ============================================================================
# TrajectoryLogger 测试
# ============================================================================

class TestTrajectoryLogger:
    @pytest.mark.asyncio
    async def test_before_after_agent(self, tmp_path):
        tl = TrajectoryLogger(output_dir=tmp_path, session_id="test1", buffer_size=1)
        ctx = _make_context()

        async def noop(c):
            pass

        await tl.before_agent(ctx, noop)
        await tl.after_agent(ctx, noop)

        lines = tl.output_path.read_text().strip().split("\n")
        assert len(lines) == 2
        assert json.loads(lines[0])["event"] == "agent_start"
        assert json.loads(lines[1])["event"] == "agent_end"

    @pytest.mark.asyncio
    async def test_model_request_response(self, tmp_path):
        tl = TrajectoryLogger(output_dir=tmp_path, session_id="test2", buffer_size=1)

        req = ModelRequest(
            messages=[UserMessage(content="hi")],
            system_prompt="test",
            tools=[],
            llm_config=_make_llm_config(),
        )
        resp = ModelResponse(
            message=AssistantMessage(
                content=[TextContent(text="hello")],
                stop_reason="end_turn",
                usage={"input_tokens": 10, "output_tokens": 5},
            ),
            request=req,
        )

        async def pass_req(r):
            return r
        async def pass_resp(r):
            return r

        await tl.before_model(req, pass_req)
        await tl.after_model(resp, pass_resp)

        lines = tl.output_path.read_text().strip().split("\n")
        assert len(lines) == 2
        assert json.loads(lines[0])["event"] == "model_request"
        assert json.loads(lines[1])["event"] == "model_response"
        assert json.loads(lines[1])["data"]["usage"]["input_tokens"] == 10

    @pytest.mark.asyncio
    async def test_tool_events(self, tmp_path):
        tl = TrajectoryLogger(output_dir=tmp_path, session_id="test3", buffer_size=1)

        req = ToolRequest(tool_call_id="tc1", tool_name="read_file", arguments={"path": "/tmp"})
        result = ToolResult(
            tool_call_id="tc1",
            tool_name="read_file",
            content=[TextContent(text="file content")],
        )

        async def pass_req(r):
            return r
        async def pass_result(r):
            return r

        await tl.pre_tool_use(req, pass_req)
        await tl.post_tool_use(result, pass_result)

        lines = tl.output_path.read_text().strip().split("\n")
        assert len(lines) == 2
        assert json.loads(lines[0])["event"] == "tool_start"
        assert json.loads(lines[1])["event"] == "tool_end"
        assert json.loads(lines[0])["data"]["tool_name"] == "read_file"

    @pytest.mark.asyncio
    async def test_buffer_flush(self, tmp_path):
        """buffer_size=5 时，4 条不写入，第 5 条触发 flush"""
        tl = TrajectoryLogger(output_dir=tmp_path, session_id="test4", buffer_size=5)

        async def noop(c):
            pass

        ctx = _make_context()
        for _ in range(4):
            await tl.before_agent(ctx, noop)

        # 还没 flush
        assert not tl.output_path.exists() or tl.output_path.read_text() == ""

        # 第 5 条触发 flush
        await tl.before_agent(ctx, noop)
        lines = tl.output_path.read_text().strip().split("\n")
        assert len(lines) == 5

    @pytest.mark.asyncio
    async def test_error_event(self, tmp_path):
        tl = TrajectoryLogger(output_dir=tmp_path, session_id="test5", buffer_size=1)
        err = AgentError(exception=ValueError("boom"), phase="model")

        async def pass_err(e):
            from packages.interceptor.types import ErrorRecovery
            return ErrorRecovery()

        await tl.error(err, pass_err)
        lines = tl.output_path.read_text().strip().split("\n")
        assert json.loads(lines[0])["event"] == "error"
        assert "boom" in json.loads(lines[0])["data"]["exception"]


# ============================================================================
# TrajectoryReplay 测试
# ============================================================================

class TestTrajectoryReplay:
    def _write_events(self, path: Path, events: list[dict]):
        with path.open("w") as f:
            for e in events:
                f.write(json.dumps(e) + "\n")

    def test_from_file(self, tmp_path):
        p = tmp_path / "test.jsonl"
        self._write_events(p, [
            {"ts": 1.0, "session_id": "s1", "event": "agent_start", "data": {"model": "test"}},
            {"ts": 2.0, "session_id": "s1", "event": "agent_end", "data": {"duration_s": 1.0, "iteration": 3}},
        ])
        replay = TrajectoryReplay.from_file(p)
        assert len(replay.events) == 2

    def test_summary(self, tmp_path):
        p = tmp_path / "test.jsonl"
        self._write_events(p, [
            {"ts": 1.0, "session_id": "s1", "event": "agent_start", "data": {"model": "claude"}},
            {"ts": 2.0, "session_id": "s1", "event": "model_request", "data": {}},
            {"ts": 3.0, "session_id": "s1", "event": "model_response", "data": {"usage": {"input_tokens": 100}}},
            {"ts": 4.0, "session_id": "s1", "event": "tool_start", "data": {"tool_name": "read_file"}},
            {"ts": 5.0, "session_id": "s1", "event": "tool_end", "data": {}},
            {"ts": 6.0, "session_id": "s1", "event": "tool_start", "data": {"tool_name": "edit_file"}},
            {"ts": 7.0, "session_id": "s1", "event": "tool_end", "data": {}},
            {"ts": 8.0, "session_id": "s1", "event": "error", "data": {"phase": "tool"}},
            {"ts": 9.0, "session_id": "s1", "event": "agent_end", "data": {"duration_s": 8.0, "iteration": 5}},
        ])
        replay = TrajectoryReplay.from_file(p)
        s = replay.summary()
        assert s.session_id == "s1"
        assert s.model == "claude"
        assert s.turns == 5
        assert s.tool_calls == 2
        assert s.errors == 1
        assert s.duration_s == 8.0
        assert s.total_events == 9

    def test_tool_sequence(self, tmp_path):
        p = tmp_path / "test.jsonl"
        self._write_events(p, [
            {"ts": 1.0, "session_id": "s1", "event": "tool_start", "data": {"tool_name": "read_file"}},
            {"ts": 2.0, "session_id": "s1", "event": "tool_start", "data": {"tool_name": "edit_file"}},
            {"ts": 3.0, "session_id": "s1", "event": "tool_start", "data": {"tool_name": "bash"}},
        ])
        replay = TrajectoryReplay.from_file(p)
        assert replay.tool_sequence() == ["read_file", "edit_file", "bash"]

    def test_filter(self, tmp_path):
        p = tmp_path / "test.jsonl"
        self._write_events(p, [
            {"ts": 1.0, "session_id": "s1", "event": "agent_start", "data": {}},
            {"ts": 2.0, "session_id": "s1", "event": "error", "data": {"phase": "model"}},
            {"ts": 3.0, "session_id": "s1", "event": "error", "data": {"phase": "tool"}},
        ])
        replay = TrajectoryReplay.from_file(p)
        errors = replay.errors()
        assert len(errors) == 2
        assert replay.filter("agent_start") == [replay.events[0]]

    def test_empty_file(self, tmp_path):
        p = tmp_path / "empty.jsonl"
        p.write_text("")
        replay = TrajectoryReplay.from_file(p)
        assert len(replay.events) == 0
        s = replay.summary()
        assert s.total_events == 0
        assert s.tool_calls == 0
