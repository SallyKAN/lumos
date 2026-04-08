"""
BenchmarkAdapter Protocol — 接入外部 benchmark 数据集的标准接口
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from ..evaluator.base import TaskSpec


@runtime_checkable
class BenchmarkAdapter(Protocol):
    """外部 benchmark 接入协议

    实现此协议以接入 SWE-bench、CC feature alignment 等榜单。
    """

    name: str

    def load_tasks(self) -> list[TaskSpec]:
        """加载任务列表"""
        ...

    def score_to_metric(self, score: float) -> dict:
        """将内部 score 转换为 benchmark 特定指标"""
        ...
