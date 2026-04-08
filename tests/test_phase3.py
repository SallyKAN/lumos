"""Phase 3 测试：Evaluator + EfficiencyEvaluator + OptimizationWorkspace + BenchmarkRunner + Optimizer"""

import json
import pytest
from pathlib import Path

from packages.optimization.evaluator.base import Evaluator, EvalResult, TaskSpec
from packages.optimization.evaluator.builtins.efficiency import EfficiencyEvaluator
from packages.optimization.trajectory.replay import TrajectoryReplay
from packages.optimization.workspace import OptimizationWorkspace
from packages.optimization.runner import BenchmarkRunner


# ============================================================================
# Helpers
# ============================================================================

def _write_trajectory(path: Path, events: list[dict]):
    with path.open("w") as f:
        for e in events:
            f.write(json.dumps(e) + "\n")


def _make_trajectory_file(tmp_path: Path, name: str = "test.jsonl") -> Path:
    p = tmp_path / name
    _write_trajectory(p, [
        {"ts": 1.0, "session_id": "s1", "event": "agent_start", "data": {"model": "test", "tools": []}},
        {"ts": 2.0, "session_id": "s1", "event": "model_request", "data": {}},
        {"ts": 3.0, "session_id": "s1", "event": "model_response", "data": {"usage": {"input_tokens": 1000, "output_tokens": 500}}},
        {"ts": 4.0, "session_id": "s1", "event": "tool_start", "data": {"tool_name": "read_file"}},
        {"ts": 5.0, "session_id": "s1", "event": "tool_end", "data": {}},
        {"ts": 6.0, "session_id": "s1", "event": "tool_start", "data": {"tool_name": "edit_file"}},
        {"ts": 7.0, "session_id": "s1", "event": "tool_end", "data": {}},
        {"ts": 8.0, "session_id": "s1", "event": "agent_end", "data": {"duration_s": 7.0, "iteration": 2}},
    ])
    return p


def _create_test_harness(path: Path, name: str = "test-harness"):
    path.mkdir(parents=True, exist_ok=True)
    (path / "HARNESS.yaml").write_text(f"name: {name}\nversion: 0.1.0\nprovides: {{}}\n")
    (path / "config").mkdir(exist_ok=True)
    (path / "config" / "overrides.yaml").write_text("max_iterations: 30\ntemperature: 0.7\n")
    return path


# ============================================================================
# Evaluator 基类测试
# ============================================================================

class TestEvaluatorBase:
    def test_eval_result_creation(self):
        r = EvalResult(score=0.85, passed=True, reason="good")
        assert r.score == 0.85
        assert r.passed is True

    def test_abstract_evaluator_cannot_instantiate(self):
        with pytest.raises(TypeError):
            Evaluator()

    def test_task_spec(self):
        t = TaskSpec(task_id="t1", description="test task")
        assert t.task_id == "t1"


# ============================================================================
# EfficiencyEvaluator 测试
# ============================================================================

class TestEfficiencyEvaluator:
    def test_basic_evaluation(self, tmp_path):
        p = _make_trajectory_file(tmp_path)
        replay = TrajectoryReplay.from_file(p)
        ev = EfficiencyEvaluator(max_expected_tool_calls=20, max_expected_tokens=50000)
        result = ev.evaluate(replay)
        assert 0.0 <= result.score <= 1.0
        assert result.evaluator_name == "efficiency"
        assert result.details["tool_calls"] == 2

    def test_high_cost_low_score(self, tmp_path):
        """超过 max 的 2 倍 → score 较低"""
        p = tmp_path / "expensive.jsonl"
        events = [
            {"ts": 1.0, "session_id": "s1", "event": "agent_start", "data": {"model": "test", "tools": []}},
        ]
        # 50 个 tool calls
        for i in range(50):
            events.append({"ts": float(i+2), "session_id": "s1", "event": "tool_start", "data": {"tool_name": f"tool_{i}"}})
            events.append({"ts": float(i+2.5), "session_id": "s1", "event": "tool_end", "data": {}})
        # 大量 tokens
        events.append({"ts": 100.0, "session_id": "s1", "event": "model_response", "data": {"usage": {"input_tokens": 80000, "output_tokens": 40000}}})
        events.append({"ts": 101.0, "session_id": "s1", "event": "agent_end", "data": {"duration_s": 100, "iteration": 10}})
        _write_trajectory(p, events)

        replay = TrajectoryReplay.from_file(p)
        ev = EfficiencyEvaluator(max_expected_tool_calls=20, max_expected_tokens=50000)
        result = ev.evaluate(replay)
        assert result.score < 0.3

    def test_perfect_efficiency(self, tmp_path):
        """0 tool calls, 0 tokens → score 接近 1.0"""
        p = tmp_path / "perfect.jsonl"
        _write_trajectory(p, [
            {"ts": 1.0, "session_id": "s1", "event": "agent_start", "data": {"model": "test", "tools": []}},
            {"ts": 2.0, "session_id": "s1", "event": "agent_end", "data": {"duration_s": 1.0, "iteration": 1}},
        ])
        replay = TrajectoryReplay.from_file(p)
        ev = EfficiencyEvaluator()
        result = ev.evaluate(replay)
        assert result.score == 1.0

    def test_configurable_thresholds(self, tmp_path):
        p = _make_trajectory_file(tmp_path)
        replay = TrajectoryReplay.from_file(p)
        # 很低的阈值 → 分数更低
        ev_strict = EfficiencyEvaluator(max_expected_tool_calls=2, max_expected_tokens=1500)
        r_strict = ev_strict.evaluate(replay)
        # 很高的阈值 → 分数更高
        ev_lenient = EfficiencyEvaluator(max_expected_tool_calls=100, max_expected_tokens=500000)
        r_lenient = ev_lenient.evaluate(replay)
        assert r_strict.score < r_lenient.score


# ============================================================================
# OptimizationWorkspace 测试
# ============================================================================

class TestOptimizationWorkspace:
    def test_init_creates_structure(self, tmp_path):
        harness = _create_test_harness(tmp_path / "harness")
        ws_mgr = OptimizationWorkspace(tmp_path / "optimization")
        ws = ws_mgr.init("test-opt", "dummy", harness)
        assert (ws / "WORKSPACE.yaml").is_file()
        assert (ws / "harness" / "HARNESS.yaml").is_file()
        assert (ws / "scores.tsv").is_file()
        assert (ws / "benchmarks").is_dir()
        assert (ws / "trajectories").is_dir()

    def test_list_workspaces(self, tmp_path):
        harness = _create_test_harness(tmp_path / "harness")
        ws_mgr = OptimizationWorkspace(tmp_path / "optimization")
        ws_mgr.init("opt-a", "dummy", harness)
        ws_mgr.init("opt-b", "dummy", harness)
        names = ws_mgr.list_workspaces()
        assert "opt-a" in names
        assert "opt-b" in names

    def test_record_and_get_scores(self, tmp_path):
        harness = _create_test_harness(tmp_path / "harness")
        ws_mgr = OptimizationWorkspace(tmp_path / "optimization")
        ws_mgr.init("test-opt", "dummy", harness)
        ws_mgr.record_score("test-opt", 1, 0.75, 0.0, "first")
        ws_mgr.record_score("test-opt", 2, 0.80, 0.75, "second")
        scores = ws_mgr.get_scores("test-opt")
        assert len(scores) == 2
        assert scores[0]["round"] == 1
        assert scores[1]["score"] == 0.80

    def test_init_idempotent_raises(self, tmp_path):
        harness = _create_test_harness(tmp_path / "harness")
        ws_mgr = OptimizationWorkspace(tmp_path / "optimization")
        ws_mgr.init("test-opt", "dummy", harness)
        with pytest.raises(FileExistsError):
            ws_mgr.init("test-opt", "dummy", harness)

    def test_delete(self, tmp_path):
        harness = _create_test_harness(tmp_path / "harness")
        ws_mgr = OptimizationWorkspace(tmp_path / "optimization")
        ws_mgr.init("test-opt", "dummy", harness)
        assert ws_mgr.delete("test-opt") is True
        assert "test-opt" not in ws_mgr.list_workspaces()

    def test_trajectory_dir(self, tmp_path):
        harness = _create_test_harness(tmp_path / "harness")
        ws_mgr = OptimizationWorkspace(tmp_path / "optimization")
        ws_mgr.init("test-opt", "dummy", harness)
        d = ws_mgr.get_trajectory_dir("test-opt", 1)
        assert d.name == "round_001"
        assert d.is_dir()


# ============================================================================
# BenchmarkRunner 测试
# ============================================================================

class TestBenchmarkRunner:
    def test_load_tasks(self, tmp_path):
        tasks_file = tmp_path / "tasks.jsonl"
        tasks_file.write_text(
            '{"task_id": "t1", "description": "task 1"}\n'
            '{"task_id": "t2", "description": "task 2"}\n'
        )
        runner = BenchmarkRunner()
        tasks = runner.load_tasks(tasks_file)
        assert len(tasks) == 2
        assert tasks[0].task_id == "t1"

    @pytest.mark.asyncio
    async def test_run_single_task(self, tmp_path):
        async def mock_agent(task, output_dir):
            p = output_dir / f"{task.task_id}.jsonl"
            _write_trajectory(p, [
                {"ts": 1.0, "session_id": "s1", "event": "agent_start", "data": {"model": "test", "tools": []}},
                {"ts": 2.0, "session_id": "s1", "event": "agent_end", "data": {"duration_s": 1.0, "iteration": 1}},
            ])
            return p

        runner = BenchmarkRunner(evaluators=[EfficiencyEvaluator()])
        tasks = [TaskSpec(task_id="t1", description="test")]
        result = await runner.run_round(tasks, mock_agent, tmp_path, round_num=1)
        assert len(result.task_results) == 1
        assert result.task_results[0].eval_result is not None
        assert result.avg_score > 0

    @pytest.mark.asyncio
    async def test_task_failure_continues(self, tmp_path):
        call_count = 0

        async def failing_then_ok(task, output_dir):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RuntimeError("boom")
            p = output_dir / f"{task.task_id}.jsonl"
            _write_trajectory(p, [
                {"ts": 1.0, "session_id": "s1", "event": "agent_start", "data": {"model": "test", "tools": []}},
                {"ts": 2.0, "session_id": "s1", "event": "agent_end", "data": {"duration_s": 1.0, "iteration": 1}},
            ])
            return p

        runner = BenchmarkRunner(evaluators=[EfficiencyEvaluator()])
        tasks = [TaskSpec(task_id="t1"), TaskSpec(task_id="t2")]
        result = await runner.run_round(tasks, failing_then_ok, tmp_path)
        assert len(result.task_results) == 2
        assert result.task_results[0].error is not None
        assert result.task_results[1].error is None

    @pytest.mark.asyncio
    async def test_task_timeout(self, tmp_path):
        import asyncio

        async def slow_agent(task, output_dir):
            await asyncio.sleep(10)
            return output_dir / "never.jsonl"

        runner = BenchmarkRunner(evaluators=[], task_timeout_s=0.1)
        tasks = [TaskSpec(task_id="t1")]
        result = await runner.run_round(tasks, slow_agent, tmp_path)
        assert result.task_results[0].error is not None
        assert "Timeout" in result.task_results[0].error
