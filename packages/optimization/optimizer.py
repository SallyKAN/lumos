"""
Lumos Optimization — 自动优化循环

lumos optimize run --rounds N 的核心逻辑。
v1 策略：hill-climbing（随机微调参数，score 提升则保留）。
"""

from __future__ import annotations

import logging
import random
from pathlib import Path
from typing import Optional

import yaml

from .workspace import OptimizationWorkspace
from .runner import BenchmarkRunner, RoundResult, AgentRunFn
from .evaluator.base import TaskSpec

logger = logging.getLogger(__name__)


class Optimizer:
    """自动优化器

    每轮：
    1. 微调 harness config 参数
    2. 跑 benchmark
    3. 评估 score
    4. score 提升 → git commit (keep)
       score 下降 → git revert (revert)
    5. 记录 scores.tsv
    """

    def __init__(
        self,
        workspace_mgr: OptimizationWorkspace,
        runner: BenchmarkRunner,
        workspace_name: str,
    ):
        self._ws_mgr = workspace_mgr
        self._runner = runner
        self._ws_name = workspace_name

    async def run(
        self,
        rounds: int,
        agent_fn: AgentRunFn,
        tasks: Optional[list[TaskSpec]] = None,
    ) -> list[RoundResult]:
        """运行 N 轮优化"""
        ws = self._ws_mgr.get_workspace(self._ws_name)

        # 加载任务
        if tasks is None:
            tasks_file = ws / "benchmarks" / "tasks.jsonl"
            if tasks_file.is_file():
                tasks = self._runner.load_tasks(tasks_file)
            else:
                tasks = []

        if not tasks:
            logger.warning("No tasks to run")
            return []

        results = []
        prev_score = 0.0

        # 获取已有分数
        existing = self._ws_mgr.get_scores(self._ws_name)
        if existing:
            prev_score = existing[-1]["score"]

        config = self._ws_mgr.load_config(self._ws_name)
        start_round = config.get("current_round", 0) + 1

        for i in range(rounds):
            round_num = start_round + i
            logger.info(f"=== Round {round_num} ===")

            # 微调参数
            self._tweak_config(ws / "harness")

            # 跑 benchmark
            traj_dir = self._ws_mgr.get_trajectory_dir(self._ws_name, round_num)
            round_result = await self._runner.run_round(
                tasks=tasks,
                agent_fn=agent_fn,
                output_dir=traj_dir,
                round_num=round_num,
            )
            results.append(round_result)

            score = round_result.avg_score
            delta = score - prev_score

            if delta >= 0:
                # 保留
                self._ws_mgr.record_score(
                    self._ws_name, round_num, score, prev_score, note="keep",
                )
                self._ws_mgr.commit_round(
                    self._ws_name, round_num,
                    f"round {round_num}: score={score:.4f} (+{delta:.4f}) KEEP",
                )
                prev_score = score
                logger.info(f"Round {round_num}: score={score:.4f} (+{delta:.4f}) → KEEP")
            else:
                # 回退
                self._ws_mgr.record_score(
                    self._ws_name, round_num, score, prev_score, note="revert",
                )
                self._ws_mgr.commit_round(
                    self._ws_name, round_num,
                    f"round {round_num}: score={score:.4f} ({delta:.4f}) REVERT",
                )
                self._ws_mgr.revert_last(self._ws_name)
                logger.info(f"Round {round_num}: score={score:.4f} ({delta:.4f}) → REVERT")

        return results

    def _tweak_config(self, harness_dir: Path) -> None:
        """v1: 随机微调 config 中的数值型参数"""
        config_dir = harness_dir / "config"
        if not config_dir.is_dir():
            return

        for cfg_file in config_dir.glob("*.yaml"):
            try:
                with cfg_file.open(encoding="utf-8") as f:
                    data = yaml.safe_load(f) or {}

                changed = self._tweak_dict(data)
                if changed:
                    with cfg_file.open("w", encoding="utf-8") as f:
                        yaml.safe_dump(data, f, default_flow_style=False)
            except Exception as e:
                logger.debug(f"Failed to tweak {cfg_file}: {e}")

    def _tweak_dict(self, d: dict, probability: float = 0.3) -> bool:
        """递归微调 dict 中的数值型字段"""
        changed = False
        for k, v in d.items():
            if isinstance(v, (int, float)) and random.random() < probability:
                # ±10% 微调
                factor = 1.0 + random.uniform(-0.1, 0.1)
                if isinstance(v, int):
                    new_val = max(1, int(v * factor))
                else:
                    new_val = round(v * factor, 4)
                if new_val != v:
                    d[k] = new_val
                    changed = True
            elif isinstance(v, dict):
                if self._tweak_dict(v, probability):
                    changed = True
        return changed
