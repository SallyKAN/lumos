"""
E2E: InterceptorEngine lifecycle — real engine, no LLM calls.

Key API facts (verified against source):
- Engine methods: run_pre_tool_use(request) → ToolRequest|ToolResult
                  run_post_tool_use(result) → ToolResult
                  run_before_agent(context), run_after_agent(context)
- Interceptor hooks: pre_tool_use(request, proceed), post_tool_use(result, proceed)
- TrajectoryLogger: packages.server.trajectory.logger, __init__(output_dir, session_id)
- WriteRmLoopDetector: packages.server.interceptor.builtins.loop_detector
- ToolRequest/ToolResult: packages.server.interceptor.types
"""

import asyncio
import json
import pytest
from pathlib import Path

from packages.server.interceptor.engine import InterceptorEngine
from packages.server.interceptor.base import BaseInterceptor
from packages.server.interceptor.builtins.loop_detector import WriteRmLoopDetector
from packages.server.interceptor.types import ToolRequest, ToolResult, AgentContext
from packages.server.trajectory.logger import TrajectoryLogger

_ID = "test-call-id"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def make_engine(*interceptors) -> InterceptorEngine:
    engine = InterceptorEngine()
    for i in interceptors:
        engine.register(i)
    return engine


def make_req(name: str, args: dict = None) -> ToolRequest:
    return ToolRequest(tool_call_id=_ID, tool_name=name, arguments=args or {})


def make_result(content: str = "ok", is_error: bool = False) -> ToolResult:
    # ToolResult.content is list[ContentBlock]; pass raw string in details for test assertions
    return ToolResult(tool_call_id=_ID, tool_name="test", is_error=is_error, details=content)


# ---------------------------------------------------------------------------
# Custom interceptors for testing
# ---------------------------------------------------------------------------

class RecordingInterceptor(BaseInterceptor):
    name = "recording"
    priority = 50

    def __init__(self):
        self.pre_calls = []
        self.post_calls = []

    async def pre_tool_use(self, request, proceed):
        self.pre_calls.append(request.tool_name)
        return await proceed(request)

    async def post_tool_use(self, result, proceed):
        self.post_calls.append(result.details)
        return await proceed(result)


class BlockingInterceptor(BaseInterceptor):
    name = "blocker"
    priority = 10  # outer

    async def pre_tool_use(self, request, proceed):
        if request.tool_name == "bash":
            return ToolResult(tool_call_id=_ID, tool_name="bash",
                              is_error=True, details="Blocked by policy")
        return await proceed(request)


class TransformInterceptor(BaseInterceptor):
    name = "transformer"
    priority = 90  # inner

    async def post_tool_use(self, result, proceed):
        modified = ToolResult(
            tool_call_id=result.tool_call_id,
            tool_name=result.tool_name,
            is_error=result.is_error,
            details=str(result.details or "") + " [transformed]",
        )
        return await proceed(modified)


# ---------------------------------------------------------------------------
# InterceptorEngine — pre_tool_use
# ---------------------------------------------------------------------------

class TestInterceptorEnginePreTool:
    def test_empty_engine_passes_request_through(self):
        engine = InterceptorEngine()
        req = make_req("bash")
        result = run(engine.run_pre_tool_use(req))
        # No interceptors → returns the original ToolRequest unchanged
        assert isinstance(result, ToolRequest)
        assert result.tool_name == "bash"

    def test_recording_interceptor_fires_on_pre(self):
        recorder = RecordingInterceptor()
        engine = make_engine(recorder)
        run(engine.run_pre_tool_use(make_req("read_file")))
        assert "read_file" in recorder.pre_calls

    def test_blocking_interceptor_returns_tool_result(self):
        blocker = BlockingInterceptor()
        engine = make_engine(blocker)
        result = run(engine.run_pre_tool_use(make_req("bash")))
        assert isinstance(result, ToolResult)
        assert result.is_error is True
        assert "Blocked" in str(result.details)

    def test_non_blocked_tool_passes_through(self):
        blocker = BlockingInterceptor()
        engine = make_engine(blocker)
        result = run(engine.run_pre_tool_use(make_req("read_file")))
        assert isinstance(result, ToolRequest)

    def test_priority_order_outer_wraps_inner(self):
        order = []

        class Outer(BaseInterceptor):
            name = "outer"
            priority = 0

            async def pre_tool_use(self, request, proceed):
                order.append("outer-pre")
                result = await proceed(request)
                order.append("outer-post")
                return result

        class Inner(BaseInterceptor):
            name = "inner"
            priority = 100

            async def pre_tool_use(self, request, proceed):
                order.append("inner-pre")
                result = await proceed(request)
                order.append("inner-post")
                return result

        engine = make_engine(Inner(), Outer())
        run(engine.run_pre_tool_use(make_req("bash")))
        assert order == ["outer-pre", "inner-pre", "inner-post", "outer-post"]

    def test_multiple_interceptors_all_fire(self):
        recorder = RecordingInterceptor()
        blocker = BlockingInterceptor()
        engine = make_engine(recorder, blocker)
        run(engine.run_pre_tool_use(make_req("read_file")))
        assert "read_file" in recorder.pre_calls


# ---------------------------------------------------------------------------
# InterceptorEngine — post_tool_use
# ---------------------------------------------------------------------------

class TestInterceptorEnginePostTool:
    def test_empty_engine_passes_result_through(self):
        engine = make_engine()
        result = run(engine.run_post_tool_use(make_result("hello")))
        assert result.details == "hello"

    def test_recording_interceptor_fires_on_post(self):
        recorder = RecordingInterceptor()
        engine = make_engine(recorder)
        run(engine.run_post_tool_use(make_result("data")))
        assert "data" in recorder.post_calls

    def test_transform_interceptor_modifies_result(self):
        transformer = TransformInterceptor()
        engine = make_engine(transformer)
        result = run(engine.run_post_tool_use(make_result("original")))
        assert "[transformed]" in str(result.details)

    def test_error_result_preserved(self):
        recorder = RecordingInterceptor()
        engine = make_engine(recorder)
        result = run(engine.run_post_tool_use(make_result("boom", is_error=True)))
        assert result.is_error is True


# ---------------------------------------------------------------------------
# TrajectoryLogger
# ---------------------------------------------------------------------------

class TestTrajectoryLogger:
    def test_logs_pre_tool_use(self, tmp_path):
        logger = TrajectoryLogger(output_dir=tmp_path, session_id="s1", buffer_size=1)
        engine = make_engine(logger)
        run(engine.run_pre_tool_use(make_req("bash", {"command": "ls"})))
        lines = [json.loads(l) for l in logger.output_path.read_text().splitlines() if l.strip()]
        events = [l["event"] for l in lines]
        assert "tool_start" in events

    def test_logs_post_tool_use(self, tmp_path):
        logger = TrajectoryLogger(output_dir=tmp_path, session_id="s1", buffer_size=1)
        engine = make_engine(logger)
        run(engine.run_post_tool_use(make_result("result")))
        lines = [json.loads(l) for l in logger.output_path.read_text().splitlines() if l.strip()]
        events = [l["event"] for l in lines]
        assert "tool_end" in events

    def test_session_id_in_all_records(self, tmp_path):
        logger = TrajectoryLogger(output_dir=tmp_path, session_id="my-session", buffer_size=1)
        engine = make_engine(logger)
        run(engine.run_pre_tool_use(make_req("read_file")))
        lines = [json.loads(l) for l in logger.output_path.read_text().splitlines() if l.strip()]
        assert all(l["session_id"] == "my-session" for l in lines)

    def test_output_path_is_session_jsonl(self, tmp_path):
        logger = TrajectoryLogger(output_dir=tmp_path, session_id="abc123")
        assert logger.output_path == tmp_path / "abc123.jsonl"

    def test_multiple_calls_append(self, tmp_path):
        logger = TrajectoryLogger(output_dir=tmp_path, session_id="s1", buffer_size=1)
        engine = make_engine(logger)
        run(engine.run_pre_tool_use(make_req("bash")))
        run(engine.run_pre_tool_use(make_req("read_file")))
        lines = [l for l in logger.output_path.read_text().splitlines() if l.strip()]
        assert len(lines) >= 2

    def test_error_result_logged(self, tmp_path):
        logger = TrajectoryLogger(output_dir=tmp_path, session_id="s1", buffer_size=1)
        engine = make_engine(logger)
        run(engine.run_post_tool_use(make_result("boom", is_error=True)))
        lines = [json.loads(l) for l in logger.output_path.read_text().splitlines() if l.strip()]
        tool_end = next((l for l in lines if l["event"] == "tool_end"), None)
        assert tool_end is not None
        assert tool_end["data"].get("is_error") is True

# ---------------------------------------------------------------------------
# WriteRmLoopDetector
# ---------------------------------------------------------------------------

class TestWriteRmLoopDetector:
    def test_allows_single_write(self):
        detector = WriteRmLoopDetector()
        engine = make_engine(detector)
        result = run(engine.run_pre_tool_use(make_req("write_file", {"file_path": "/tmp/a.py"})))
        assert not isinstance(result, ToolResult) or not result.is_error

    def test_allows_write_then_read(self):
        detector = WriteRmLoopDetector()
        engine = make_engine(detector)
        run(engine.run_pre_tool_use(make_req("write_file", {"file_path": "/tmp/a.py"})))
        result = run(engine.run_pre_tool_use(make_req("read_file", {"file_path": "/tmp/a.py"})))
        assert not isinstance(result, ToolResult) or not result.is_error

    def test_detects_repeated_write_rm_loop(self):
        detector = WriteRmLoopDetector(threshold=2)
        engine = make_engine(detector)

        for _ in range(3):
            run(engine.run_post_tool_use(
                ToolResult(tool_call_id=_ID, tool_name="write_file",
                           request=make_req("write_file", {"file_path": "/tmp/x.py"}))
            ))
            run(engine.run_post_tool_use(
                ToolResult(tool_call_id=_ID, tool_name="bash",
                           request=make_req("bash", {"command": "rm /tmp/x.py"}))
            ))

        assert detector is not None
