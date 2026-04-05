"""
Lumos Optimization — 优化 Workspace 管理

每个优化任务是一个独立目录，包含 harness 副本、benchmark 任务集、
trajectory 记录、分数历史。用 git 做 keep-or-revert。
"""

from __future__ import annotations

import json
import logging
import shutil
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import yaml

logger = logging.getLogger(__name__)


@dataclass
class WorkspaceConfig:
    """优化 workspace 配置"""
    name: str
    benchmark: str
    harness_source: str
    created_at: str = ""
    current_round: int = 0


class OptimizationWorkspace:
    """优化 Workspace 管理器

    目录结构：
        .lumos/optimization/<name>/
        ├── WORKSPACE.yaml
        ├── harness/          (被优化的 harness 副本，git tracked)
        ├── benchmarks/       (任务集，只读)
        │   └── tasks.jsonl
        ├── evaluators/       (评估函数，只读)
        ├── trajectories/     (每轮行为日志)
        │   ├── round_001/
        │   └── round_002/
        ├── scores.tsv        (分数历史)
        └── .git/             (每轮一个 commit)
    """

    def __init__(self, base_dir: Path):
        """
        Args:
            base_dir: .lumos/optimization/ 目录
        """
        self._base = Path(base_dir)
        self._base.mkdir(parents=True, exist_ok=True)

    def init(
        self,
        name: str,
        benchmark: str,
        harness_dir: Path,
        tasks_jsonl: Optional[Path] = None,
    ) -> Path:
        """初始化一个优化 workspace

        Returns:
            workspace 目录路径
        """
        ws = self._base / name
        if ws.exists():
            raise FileExistsError(f"Workspace '{name}' already exists at {ws}")

        ws.mkdir(parents=True)

        # 子目录
        (ws / "benchmarks").mkdir()
        (ws / "evaluators").mkdir()
        (ws / "trajectories").mkdir()

        # 复制 harness
        shutil.copytree(harness_dir, ws / "harness")

        # 复制 tasks.jsonl
        if tasks_jsonl and tasks_jsonl.is_file():
            shutil.copy2(tasks_jsonl, ws / "benchmarks" / "tasks.jsonl")

        # 写 WORKSPACE.yaml
        config = WorkspaceConfig(
            name=name,
            benchmark=benchmark,
            harness_source=str(harness_dir),
            created_at=datetime.now(timezone.utc).isoformat(),
        )
        with (ws / "WORKSPACE.yaml").open("w", encoding="utf-8") as f:
            yaml.safe_dump({
                "name": config.name,
                "benchmark": config.benchmark,
                "harness_source": config.harness_source,
                "created_at": config.created_at,
                "current_round": 0,
            }, f, default_flow_style=False)

        # 初始化 scores.tsv
        (ws / "scores.tsv").write_text("round\tscore\tdelta\tdate\tnote\n", encoding="utf-8")

        # 初始化 git
        self._git(ws, "init")
        self._git(ws, "add", "-A")
        self._git(ws, "commit", "-m", "init: baseline harness")

        logger.info(f"Initialized optimization workspace: {name}")
        return ws

    def list_workspaces(self) -> list[str]:
        """列出所有优化 workspace"""
        names = []
        for d in sorted(self._base.iterdir()):
            if d.is_dir() and (d / "WORKSPACE.yaml").is_file():
                names.append(d.name)
        return names

    def get_workspace(self, name: str) -> Path:
        """获取 workspace 路径"""
        ws = self._base / name
        if not ws.exists():
            raise FileNotFoundError(f"Workspace '{name}' not found")
        return ws

    def load_config(self, name: str) -> dict:
        """加载 workspace 配置"""
        ws = self.get_workspace(name)
        with (ws / "WORKSPACE.yaml").open(encoding="utf-8") as f:
            return yaml.safe_load(f) or {}

    def record_score(
        self,
        name: str,
        round_num: int,
        score: float,
        prev_score: float = 0.0,
        note: str = "",
    ) -> None:
        """记录一轮分数"""
        ws = self.get_workspace(name)
        delta = round(score - prev_score, 4)
        date = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")
        line = f"{round_num}\t{score:.4f}\t{delta:+.4f}\t{date}\t{note}\n"
        with (ws / "scores.tsv").open("a", encoding="utf-8") as f:
            f.write(line)

    def get_scores(self, name: str) -> list[dict]:
        """读取分数历史"""
        ws = self.get_workspace(name)
        scores = []
        lines = (ws / "scores.tsv").read_text(encoding="utf-8").strip().split("\n")
        if len(lines) <= 1:
            return scores
        for line in lines[1:]:  # skip header
            parts = line.split("\t")
            if len(parts) >= 4:
                scores.append({
                    "round": int(parts[0]),
                    "score": float(parts[1]),
                    "delta": float(parts[2]),
                    "date": parts[3],
                    "note": parts[4] if len(parts) > 4 else "",
                })
        return scores

    def commit_round(self, name: str, round_num: int, message: str = "") -> None:
        """Git commit 当前轮次的变更"""
        ws = self.get_workspace(name)
        msg = message or f"round {round_num}"
        self._git(ws, "add", "-A")
        self._git(ws, "commit", "-m", msg, "--allow-empty")

    def revert_last(self, name: str) -> bool:
        """Revert 上一次 commit"""
        ws = self.get_workspace(name)
        try:
            self._git(ws, "revert", "--no-edit", "HEAD")
            return True
        except Exception as e:
            logger.error(f"Revert failed: {e}")
            return False

    def get_trajectory_dir(self, name: str, round_num: int) -> Path:
        """获取某轮的 trajectory 目录"""
        ws = self.get_workspace(name)
        d = ws / "trajectories" / f"round_{round_num:03d}"
        d.mkdir(parents=True, exist_ok=True)
        return d

    def delete(self, name: str) -> bool:
        """删除 workspace"""
        ws = self._base / name
        if ws.exists():
            shutil.rmtree(ws)
            return True
        return False

    @staticmethod
    def _git(cwd: Path, *args: str) -> str:
        """执行 git 命令"""
        result = subprocess.run(
            ["git"] + list(args),
            cwd=cwd,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0 and "nothing to commit" not in result.stdout:
            logger.debug(f"git {' '.join(args)}: {result.stderr.strip()}")
        return result.stdout.strip()
