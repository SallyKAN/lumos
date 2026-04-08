"""
Lumos Optimization — Benchmark Runner

批量运行 benchmark 任务集，收集 trajectory。
v1 单线程串行。
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Awaitable, Optional

from .evaluator.base import Evaluator, EvalResult, TaskSpec
from .trajectory.replay import TrajectoryReplay

logger = logging.getLogger(__name__)


@dataclass
class TaskResult:
    """单个任务的运行结果"""
    task_id: str
    trajectory_path: Optional[Path] = None
    eval_result: Optional[EvalResult] = None
    error: Optional[str] = None
    duration_s: float = 0.0


@dataclass
class RoundResult:
    """一轮 benchmark 的结果"""
    round_num: int
    task_results: list[TaskResult] = field(default_factory=list)
    avg_score: float = 0.0
    total_duration_s: float = 0.0

    def compute_avg(self) -> float:
        scores = [r.eval_result.score for r in self.task_results if r.eval_result]
        self.avg_score = sum(scores) / len(scores) if scores else 0.0
        return self.avg_score


# Agent 运行函数签名：接收 task spec，返回 trajectory JSONL 路径
AgentRunFn = Callable[[TaskSpec, Path], Awaitable[Path]]


class BenchmarkRunner:
    """Benchmark 运行器

    用法:
        runner = BenchmarkRunner(evaluators=[EfficiencyEvaluator()])
        result = await runner.run_round(
            tasks=tasks,
            agent_fn=my_agent_fn,
            output_dir=trajectory_dir,
            round_num=1,
        )
    """

    def __init__(
        self,
        evaluators: Optional[list[Evaluator]] = None,
        task_timeout_s: float = 300,
    ):
        self._evaluators = evaluators or []
        self._task_timeout = task_timeout_s

    def load_tasks(self, tasks_jsonl: Path) -> list[TaskSpec]:
        """从 tasks.jsonl 加载任务"""
        tasks = []
        for line in tasks_jsonl.read_text(encoding="utf-8").strip().split("\n"):
            if not line.strip():
                continue
            raw = json.loads(line)
            tasks.append(TaskSpec(
                task_id=raw.get("task_id", raw.get("id", "")),
                description=raw.get("description", ""),
                expected=raw.get("expected"),
                metadata=raw,
            ))
        return tasks

    async def run_round(
        self,
        tasks: list[TaskSpec],
        agent_fn: AgentRunFn,
        output_dir: Path,
        round_num: int = 1,
    ) -> RoundResult:
        """运行一轮 benchmark"""
        import asyncio

        result = RoundResult(round_num=round_num)
        start = time.time()

        for task in tasks:
            task_result = await self._run_task(task, agent_fn, output_dir)
            result.task_results.append(task_result)

        result.total_duration_s = round(time.time() - start, 2)
        result.compute_avg()
        return result

    async def _run_task(
        self,
        task: TaskSpec,
        agent_fn: AgentRunFn,
        output_dir: Path,
    ) -> TaskResult:
        """运行单个任务"""
        import asyncio

        start = time.time()
        try:
            trajectory_path = await asyncio.wait_for(
                agent_fn(task, output_dir),
                timeout=self._task_timeout,
            )

            # 评估
            replay = TrajectoryReplay.from_file(trajectory_path)
            eval_results = []
            for evaluator in self._evaluators:
                eval_results.append(evaluator.evaluate(replay, task))

            # 取平均分
            avg_eval = None
            if eval_results:
                avg_score = sum(r.score for r in eval_results) / len(eval_results)
                avg_eval = EvalResult(
                    score=round(avg_score, 4),
                    passed=all(r.passed for r in eval_results),
                    reason="; ".join(r.reason for r in eval_results),
                    evaluator_name="aggregate",
                )

            return TaskResult(
                task_id=task.task_id,
                trajectory_path=trajectory_path,
                eval_result=avg_eval,
                duration_s=round(time.time() - start, 2),
            )

        except asyncio.TimeoutError:
            logger.warning(f"Task {task.task_id} timed out after {self._task_timeout}s")
            return TaskResult(
                task_id=task.task_id,
                error=f"Timeout after {self._task_timeout}s",
                duration_s=round(time.time() - start, 2),
            )
        except Exception as e:
            logger.error(f"Task {task.task_id} failed: {e}")
            return TaskResult(
                task_id=task.task_id,
                error=str(e),
                duration_s=round(time.time() - start, 2),
            )
