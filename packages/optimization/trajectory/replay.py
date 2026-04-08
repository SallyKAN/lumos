"""
Lumos Trajectory — 行为轨迹重放与分析

从 JSONL 文件加载 trajectory，提供统计和查询接口。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional


@dataclass
class TrajectorySummary:
    """轨迹摘要"""
    session_id: str = ""
    turns: int = 0
    tool_calls: int = 0
    errors: int = 0
    duration_s: float = 0.0
    model: str = ""
    total_events: int = 0
    usage: Optional[dict[str, int]] = None


@dataclass
class TrajectoryEvent:
    """单个轨迹事件"""
    ts: float
    session_id: str
    event: str
    data: dict[str, Any] = field(default_factory=dict)


class TrajectoryReplay:
    """轨迹重放器

    从 JSONL 文件加载事件序列，提供分析接口。

    用法:
        replay = TrajectoryReplay.from_file("session_abc.jsonl")
        summary = replay.summary()
        tools = replay.tool_sequence()
    """

    def __init__(self, events: list[TrajectoryEvent]):
        self._events = events

    @classmethod
    def from_file(cls, path: Path | str) -> TrajectoryReplay:
        """从 JSONL 文件加载"""
        path = Path(path)
        events = []
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                raw = json.loads(line)
                events.append(TrajectoryEvent(
                    ts=raw.get("ts", 0),
                    session_id=raw.get("session_id", ""),
                    event=raw.get("event", ""),
                    data=raw.get("data", {}),
                ))
        return cls(events)

    @property
    def events(self) -> list[TrajectoryEvent]:
        return list(self._events)

    def summary(self) -> TrajectorySummary:
        """生成轨迹摘要"""
        s = TrajectorySummary(total_events=len(self._events))

        model_requests = 0
        for e in self._events:
            if e.event == "agent_start":
                s.session_id = e.session_id
                s.model = e.data.get("model", "")
            elif e.event == "agent_end":
                s.duration_s = e.data.get("duration_s", 0.0)
                s.turns = e.data.get("iteration", 0)
            elif e.event == "model_request":
                model_requests += 1
            elif e.event == "model_response":
                s.usage = e.data.get("usage") or s.usage
            elif e.event == "tool_start":
                s.tool_calls += 1
            elif e.event == "error":
                s.errors += 1

        # turns 可能没被 agent_end 记录（如果 agent 异常退出）
        if s.turns == 0:
            s.turns = model_requests

        return s

    def tool_sequence(self) -> list[str]:
        """返回工具调用序列（按时间顺序）"""
        return [
            e.data.get("tool_name", "unknown")
            for e in self._events
            if e.event == "tool_start"
        ]

    def errors(self) -> list[TrajectoryEvent]:
        """返回所有错误事件"""
        return [e for e in self._events if e.event == "error"]

    def filter(self, event_type: str) -> list[TrajectoryEvent]:
        """按事件类型过滤"""
        return [e for e in self._events if e.event == event_type]
