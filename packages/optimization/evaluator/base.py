"""
Lumos Evaluator — 不可变评估锚点基类

Evaluator 是自优化闭环的"尺子"——量化衡量 harness 配置的效果。
一旦建立只追加不修改（immutable anchor 约定）。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Optional

from ..trajectory.replay import TrajectoryReplay


@dataclass
class EvalResult:
    """评估结果"""
    score: float  # 0.0 - 1.0
    passed: bool = True
    reason: str = ""
    details: dict[str, Any] = field(default_factory=dict)
    evaluator_name: str = ""


@dataclass
class TaskSpec:
    """Benchmark 任务规格"""
    task_id: str
    description: str = ""
    expected: Any = None
    metadata: dict[str, Any] = field(default_factory=dict)


class Evaluator(ABC):
    """评估器抽象基类

    子类实现 evaluate() 方法，接收 trajectory 和 task spec，返回 EvalResult。
    Evaluator 与 agent 在概念上分离——evaluator 不能修改 agent 行为。

    Example:
        class MyEvaluator(Evaluator):
            name = "my-evaluator"

            def evaluate(self, trajectory, task=None):
                summary = trajectory.summary()
                score = 1.0 if summary.tool_calls < 10 else 0.5
                return EvalResult(score=score, evaluator_name=self.name)
    """

    name: str = "unnamed"

    @abstractmethod
    def evaluate(
        self,
        trajectory: TrajectoryReplay,
        task: Optional[TaskSpec] = None,
    ) -> EvalResult:
        """评估一个 trajectory

        Args:
            trajectory: 行为轨迹重放器
            task: 可选的任务规格（benchmark 场景下使用）

        Returns:
            EvalResult
        """
        ...
