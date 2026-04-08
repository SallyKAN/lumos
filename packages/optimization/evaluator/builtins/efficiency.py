"""
Lumos Evaluator Builtin — 效率评估器

衡量 agent 用了多少步骤和 token 完成任务。
分数公式：1.0 / (1.0 + tool_ratio + token_ratio)
"""

from __future__ import annotations

from typing import Optional

from ..base import Evaluator, EvalResult, TaskSpec
from ...trajectory.replay import TrajectoryReplay


class EfficiencyEvaluator(Evaluator):
    """效率评估器

    评估维度：
    - tool_calls vs max_expected_tool_calls
    - total tokens (from usage) vs max_expected_tokens
    """

    name = "efficiency"

    def __init__(
        self,
        max_expected_tool_calls: int = 20,
        max_expected_tokens: int = 50000,
    ):
        self._max_tools = max_expected_tool_calls
        self._max_tokens = max_expected_tokens

    def evaluate(
        self,
        trajectory: TrajectoryReplay,
        task: Optional[TaskSpec] = None,
    ) -> EvalResult:
        summary = trajectory.summary()

        tool_ratio = summary.tool_calls / max(self._max_tools, 1)
        
        # 从 trajectory 事件中累计 token usage
        total_tokens = self._extract_total_tokens(trajectory)
        token_ratio = total_tokens / max(self._max_tokens, 1)

        score = 1.0 / (1.0 + tool_ratio + token_ratio)
        score = round(min(max(score, 0.0), 1.0), 4)

        return EvalResult(
            score=score,
            passed=score > 0.2,
            reason=f"tool_calls={summary.tool_calls}, tokens={total_tokens}",
            details={
                "tool_calls": summary.tool_calls,
                "total_tokens": total_tokens,
                "tool_ratio": round(tool_ratio, 4),
                "token_ratio": round(token_ratio, 4),
                "duration_s": summary.duration_s,
                "turns": summary.turns,
            },
            evaluator_name=self.name,
        )

    def _extract_total_tokens(self, trajectory: TrajectoryReplay) -> int:
        """从 model_response 事件中累计 token"""
        total = 0
        for event in trajectory.filter("model_response"):
            usage = event.data.get("usage")
            if usage and isinstance(usage, dict):
                total += usage.get("input_tokens", 0)
                total += usage.get("output_tokens", 0)
        return total
