"""
Lumos Trajectory — 行为轨迹记录器

作为 Interceptor 实现，自动记录 agent 的每个生命周期事件到 JSONL 文件。
priority=1（最外层），确保记录所有事件包括被其他 interceptor 修改后的结果。
"""

from __future__ import annotations

import json
import time
import uuid
import logging
from pathlib import Path
from typing import Any, Optional

from packages.interceptor.base import BaseInterceptor
from packages.interceptor.types import (
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

logger = logging.getLogger(__name__)


class TrajectoryLogger(BaseInterceptor):
    """行为轨迹记录器

    记录 agent 运行过程中的所有关键事件到 JSONL 文件。
    每个 session 一个文件，文件名为 {session_id}.jsonl。

    事件类型：
    - agent_start / agent_end
    - model_request / model_response
    - tool_start / tool_end
    - stop_check
    - error
    """

    name = "trajectory-logger"
    priority = 1  # 最外层，记录一切

    def __init__(
        self,
        output_dir: Path | str,
        session_id: Optional[str] = None,
        buffer_size: int = 10,
    ):
        self._output_dir = Path(output_dir)
        self._session_id = session_id or uuid.uuid4().hex[:12]
        self._buffer_size = buffer_size
        self._buffer: list[dict] = []
        self._start_time: float = 0
        self._output_dir.mkdir(parents=True, exist_ok=True)

    @property
    def output_path(self) -> Path:
        return self._output_dir / f"{self._session_id}.jsonl"

    def _record(self, event_type: str, data: dict | None = None) -> None:
        """记录一个事件到 buffer"""
        entry = {
            "ts": time.time(),
            "session_id": self._session_id,
            "event": event_type,
        }
        if data:
            entry["data"] = data
        self._buffer.append(entry)
        if len(self._buffer) >= self._buffer_size:
            self._flush()

    def _flush(self) -> None:
        """将 buffer 写入文件"""
        if not self._buffer:
            return
        try:
            with self.output_path.open("a", encoding="utf-8") as f:
                for entry in self._buffer:
                    f.write(json.dumps(entry, ensure_ascii=False, default=str) + "\n")
            self._buffer.clear()
        except Exception as e:
            logger.error(f"TrajectoryLogger flush error: {e}")

    def _safe_messages_summary(self, messages: list) -> int:
        """返回消息数量（不序列化完整内容，避免过大）"""
        return len(messages)

    # ================================================================
    # Interceptor 生命周期方法
    # ================================================================

    async def before_agent(self, context: AgentContext, proceed):
        self._start_time = time.time()
        self._record("agent_start", {
            "tools": [t.name for t in context.tools],
            "model": context.llm_config.model,
            "message_count": self._safe_messages_summary(context.messages),
        })
        return await proceed(context)

    async def after_agent(self, context: AgentContext, proceed):
        self._record("agent_end", {
            "iteration": context.iteration,
            "message_count": self._safe_messages_summary(context.messages),
            "duration_s": round(time.time() - self._start_time, 2),
        })
        self._flush()  # 确保 session 结束时全部写入
        return await proceed(context)

    async def before_model(self, request: ModelRequest, proceed):
        self._record("model_request", {
            "model": request.llm_config.model,
            "message_count": self._safe_messages_summary(request.messages),
            "tool_count": len(request.tools),
        })
        return await proceed(request)

    async def after_model(self, response: ModelResponse, proceed):
        msg = response.message
        self._record("model_response", {
            "has_tool_calls": len(msg.tool_calls) > 0,
            "tool_call_count": len(msg.tool_calls),
            "tool_names": [tc.name for tc in msg.tool_calls],
            "stop_reason": msg.stop_reason,
            "usage": msg.usage,
            "text_length": len(msg.text),
        })
        return await proceed(response)

    async def pre_tool_use(self, request: ToolRequest, proceed):
        self._record("tool_start", {
            "tool_call_id": request.tool_call_id,
            "tool_name": request.tool_name,
            "arguments": request.arguments,
        })
        return await proceed(request)

    async def post_tool_use(self, result: ToolResult, proceed):
        text = ""
        if result.content:
            from packages.core.types import TextContent
            text = "".join(
                b.text for b in result.content if isinstance(b, TextContent)
            )
        self._record("tool_end", {
            "tool_call_id": result.tool_call_id,
            "tool_name": result.tool_name,
            "is_error": result.is_error,
            "result_length": len(text),
        })
        return await proceed(result)

    async def stop(self, context: StopContext, proceed):
        self._record("stop_check", {
            "reason": context.reason,
        })
        return await proceed(context)

    async def error(self, error: AgentError, proceed):
        self._record("error", {
            "phase": error.phase,
            "exception": str(error.exception),
        })
        return await proceed(error)
