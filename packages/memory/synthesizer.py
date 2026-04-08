"""
Lumos Memory — 记忆合成器

从 learnings.jsonl 生成 active_insights.md。
三层时间衰减：Recent (< 2 周) / Medium (2-8 周) / Foundational (> 8 周)。
"""

from __future__ import annotations

import json
import logging
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

RECENT_DAYS = 14
MEDIUM_DAYS = 56  # 8 weeks


@dataclass
class LearningEntry:
    """一条学习记录"""
    ts: datetime
    session_id: str
    entry_type: str  # "reflection" | "trajectory_summary"
    lesson: str
    context: str
    source: str
    raw: dict


class MemorySynthesizer:
    """从 learnings.jsonl 生成 active_insights.md

    触发时机：
    - 每日一次（cron / heartbeat）
    - session 结束时（如果距上次 synthesis > 24h）
    """

    def __init__(self, min_foundational_count: int = 2):
        self._min_foundational = min_foundational_count

    def synthesize(self, jsonl_path: Path, output_path: Path) -> int:
        """执行合成

        Args:
            jsonl_path: learnings.jsonl 路径
            output_path: active_insights.md 输出路径

        Returns:
            处理的条目数
        """
        entries = self._load_entries(jsonl_path)
        if not entries:
            output_path.write_text("# Active Insights\n\nNo insights yet.\n", encoding="utf-8")
            return 0

        now = datetime.now(timezone.utc)

        recent = [e for e in entries if (now - e.ts).days <= RECENT_DAYS]
        medium = [e for e in entries if RECENT_DAYS < (now - e.ts).days <= MEDIUM_DAYS]
        old = [e for e in entries if (now - e.ts).days > MEDIUM_DAYS]

        sections = ["# Active Insights\n"]

        # Recent: 完整 lesson + context
        sections.append("## Recent (Last 2 Weeks)\n")
        if recent:
            for e in recent:
                sections.append(self._format_full(e))
        else:
            sections.append("No recent insights.\n")

        # Medium: 按主题聚合
        sections.append("\n## Medium (2-8 Weeks)\n")
        if medium:
            themes = self._cluster_by_theme(medium)
            for theme, entries_list in themes.items():
                sections.append(f"### {theme}\n")
                for e in entries_list:
                    sections.append(f"- {e.lesson}\n")
                sections.append("")
        else:
            sections.append("No medium-term insights.\n")

        # Foundational: 核心原则
        sections.append("\n## Foundational\n")
        if old:
            principles = self._extract_principles(old)
            if principles:
                for p in principles:
                    sections.append(f"- {p}\n")
            else:
                sections.append("No foundational principles yet.\n")
        else:
            sections.append("No foundational principles yet.\n")

        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text("\n".join(sections), encoding="utf-8")
        return len(entries)

    def _load_entries(self, path: Path) -> list[LearningEntry]:
        """从 JSONL 加载条目"""
        if not path.is_file():
            return []

        entries = []
        for line in path.read_text(encoding="utf-8").strip().split("\n"):
            if not line.strip():
                continue
            try:
                raw = json.loads(line)
                ts_str = raw.get("ts", "")
                if isinstance(ts_str, (int, float)):
                    ts = datetime.fromtimestamp(ts_str, tz=timezone.utc)
                else:
                    ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))

                entries.append(LearningEntry(
                    ts=ts,
                    session_id=raw.get("session_id", ""),
                    entry_type=raw.get("type", "reflection"),
                    lesson=raw.get("lesson", ""),
                    context=raw.get("context", ""),
                    source=raw.get("source", ""),
                    raw=raw,
                ))
            except Exception as e:
                logger.warning(f"Failed to parse learning entry: {e}")

        return sorted(entries, key=lambda e: e.ts, reverse=True)

    def _format_full(self, entry: LearningEntry) -> str:
        """格式化完整条目"""
        date_str = entry.ts.strftime("%Y-%m-%d")
        lines = [f"**[{date_str}]** {entry.lesson}"]
        if entry.context:
            lines.append(f"  > {entry.context}")
        if entry.source:
            lines.append(f"  _Source: {entry.source}_")
        lines.append("")
        return "\n".join(lines)

    def _cluster_by_theme(self, entries: list[LearningEntry]) -> dict[str, list[LearningEntry]]:
        """按主题聚合（v1: 简单关键词匹配）"""
        themes: dict[str, list[LearningEntry]] = defaultdict(list)

        keywords = {
            "Context & Memory": ["context", "memory", "token", "压缩", "上下文"],
            "Tool Usage": ["tool", "工具", "bash", "file", "edit"],
            "Error Handling": ["error", "错误", "exception", "retry", "失败"],
            "Performance": ["performance", "性能", "slow", "fast", "效率"],
            "Architecture": ["architecture", "架构", "design", "设计", "pattern"],
        }

        for entry in entries:
            text = (entry.lesson + " " + entry.context).lower()
            matched = False
            for theme, kws in keywords.items():
                if any(kw in text for kw in kws):
                    themes[theme].append(entry)
                    matched = True
                    break
            if not matched:
                themes["General"].append(entry)

        return dict(themes)

    def _extract_principles(self, entries: list[LearningEntry]) -> list[str]:
        """从旧条目提取核心原则（v1: 出现 2+ 次的主题）"""
        themes = self._cluster_by_theme(entries)
        principles = []
        for theme, entries_list in themes.items():
            if len(entries_list) >= self._min_foundational:
                # 取最常见的 lesson 作为原则
                lessons = [e.lesson for e in entries_list if e.lesson]
                if lessons:
                    principles.append(f"[{theme}] {lessons[0]}")
        return principles
