"""Phase 2 测试：PromptComposer + WorkspaceLoader + ProjectScanner + HarnessManager + Compose + MemorySynthesizer"""

import json
import pytest
from pathlib import Path
from datetime import datetime, timezone, timedelta

from packages.capability.prompt_composer import PromptComposer, PromptSection
from packages.capability.workspace_loader import WorkspaceLoader
from packages.capability.project_scanner import ProjectScanner
from packages.harness.manager import HarnessManager
from packages.harness.loader import HarnessLoader
from packages.harness.compose import compose_harness
from packages.memory.synthesizer import MemorySynthesizer
from packages.cli.commands.init_cmd import run_init
from packages.cli.commands.setup_cmd import run_setup


# ============================================================================
# PromptComposer 测试
# ============================================================================

class TestPromptSection:
    def test_to_prompt(self):
        s = PromptSection(name="Identity", content="I am Lumos", priority=1)
        assert "=== IDENTITY ===" in s.to_prompt()
        assert "I am Lumos" in s.to_prompt()

    def test_empty_content(self):
        s = PromptSection(name="Empty", content="", priority=5)
        assert s.to_prompt() == ""

    def test_token_estimate(self):
        s = PromptSection(name="Test", content="a" * 400, priority=1)
        assert s.token_estimate == 100  # 400 / 4


class TestPromptComposer:
    def test_compose_with_workspace(self, tmp_path):
        # 创建 workspace 文件
        global_ws = tmp_path / "global"
        global_ws.mkdir()
        (global_ws / "IDENTITY.md").write_text("I am TestBot")
        (global_ws / "AGENT.md").write_text("Be helpful")
        (global_ws / "USER.md").write_text("User: Snape")

        project = tmp_path / "project"
        project.mkdir()
        (project / "LUMOS.md").write_text("Python project")

        loader = WorkspaceLoader(global_path=global_ws, project_root=project)
        composer = PromptComposer(workspace_loader=loader)
        prompt = composer.compose()

        assert "TestBot" in prompt
        assert "Be helpful" in prompt
        assert "Snape" in prompt
        assert "Python project" in prompt

    def test_fallback_when_no_files(self):
        """没有 workspace 文件时，使用内置默认规则"""
        composer = PromptComposer(fallback_prompt="DEFAULT PROMPT")
        prompt = composer.compose()
        # 现在即使没有 workspace 文件，也会用 BUILTIN_IDENTITY + BUILTIN_AGENT_RULES
        assert "Lumos" in prompt
        assert "工具" in prompt

    def test_compression_order(self):
        """L8 先被压缩，L1 不动"""
        loader_mock = type("Mock", (), {"load_file": lambda self, f: "x" * 4000})()
        composer = PromptComposer(
            workspace_loader=loader_mock,
            active_insights="insight " * 2000,
            token_budget=500,
        )
        prompt = composer.compose()
        # L1 Identity 应该完整保留
        assert "=== IDENTITY ===" in prompt

    def test_compose_with_harness_prompts(self, tmp_path):
        global_ws = tmp_path / "global"
        global_ws.mkdir()
        (global_ws / "IDENTITY.md").write_text("Bot")

        loader = WorkspaceLoader(global_path=global_ws)
        composer = PromptComposer(
            workspace_loader=loader,
            harness_prompts=["Always respond in JSON"],
        )
        prompt = composer.compose()
        assert "Always respond in JSON" in prompt

    def test_compose_with_runtime_context(self, tmp_path):
        global_ws = tmp_path / "global"
        global_ws.mkdir()
        (global_ws / "IDENTITY.md").write_text("Bot")

        loader = WorkspaceLoader(global_path=global_ws)
        composer = PromptComposer(workspace_loader=loader)
        prompt = composer.compose(runtime_context={"cwd": "/tmp/project", "git_branch": "main"})
        assert "/tmp/project" in prompt


# ============================================================================
# WorkspaceLoader 测试
# ============================================================================

class TestWorkspaceLoader:
    def test_project_overrides_global(self, tmp_path):
        global_ws = tmp_path / "global"
        global_ws.mkdir()
        (global_ws / "IDENTITY.md").write_text("global identity")

        project = tmp_path / "project"
        (project / ".lumos").mkdir(parents=True)
        (project / ".lumos" / "IDENTITY.md").write_text("project identity")

        loader = WorkspaceLoader(global_path=global_ws, project_root=project)
        assert loader.load_file("IDENTITY.md") == "project identity"

    def test_lumos_md_cascade(self, tmp_path):
        project = tmp_path / "project"
        (project / "src").mkdir(parents=True)
        (project / "LUMOS.md").write_text("root instructions")
        (project / "src" / "LUMOS.md").write_text("src instructions")

        loader = WorkspaceLoader(project_root=project, cwd=project / "src")
        content = loader.load_file("LUMOS.md")
        assert "root instructions" in content
        assert "src instructions" in content

    def test_claude_md_fallback(self, tmp_path):
        project = tmp_path / "project"
        project.mkdir()
        (project / "CLAUDE.md").write_text("claude instructions")

        loader = WorkspaceLoader(project_root=project)
        content = loader.load_file("LUMOS.md")
        assert "claude instructions" in content

    def test_missing_files_graceful(self, tmp_path):
        loader = WorkspaceLoader(global_path=tmp_path / "nonexistent")
        assert loader.load_file("IDENTITY.md") is None

    def test_load_memory(self, tmp_path):
        global_ws = tmp_path / "global"
        (global_ws / "memory").mkdir(parents=True)
        (global_ws / "memory" / "active_insights.md").write_text("global insight")

        loader = WorkspaceLoader(global_path=global_ws)
        assert "global insight" in loader.load_memory()


# ============================================================================
# ProjectScanner 测试
# ============================================================================

class TestProjectScanner:
    def test_detect_python(self, tmp_path):
        (tmp_path / "pyproject.toml").write_text('[project]\nname = "test"')
        info = ProjectScanner(tmp_path).scan()
        assert info.language == "python"
        assert info.test_cmd == "pytest"

    def test_detect_rust(self, tmp_path):
        (tmp_path / "Cargo.toml").write_text('[package]\nname = "test"')
        info = ProjectScanner(tmp_path).scan()
        assert info.language == "rust"
        assert info.build_cmd == "cargo build"

    def test_detect_node(self, tmp_path):
        (tmp_path / "package.json").write_text('{"name": "test"}')
        info = ProjectScanner(tmp_path).scan()
        assert info.language == "javascript"

    def test_detect_unknown(self, tmp_path):
        info = ProjectScanner(tmp_path).scan()
        assert info.language == "unknown"

    def test_detect_python_framework(self, tmp_path):
        (tmp_path / "pyproject.toml").write_text('[project]\ndependencies = ["fastapi"]')
        info = ProjectScanner(tmp_path).scan()
        assert info.framework == "fastapi"


# ============================================================================
# HarnessManager 测试
# ============================================================================

def _create_test_harness(path: Path, name: str = "test-harness"):
    path.mkdir(parents=True, exist_ok=True)
    (path / "HARNESS.yaml").write_text(f"name: {name}\nversion: 0.1.0\nprovides: {{}}\n")
    (path / "prompts").mkdir(exist_ok=True)
    return path


class TestHarnessManager:
    def test_install_and_list(self, tmp_path):
        harness_src = _create_test_harness(tmp_path / "src-harness", "my-harness")
        mgr = HarnessManager(global_path=tmp_path / "lumos")
        mgr.install(harness_src)
        assert "my-harness" in mgr.list_installed()

    def test_use_and_current(self, tmp_path):
        harness_src = _create_test_harness(tmp_path / "src", "h1")
        mgr = HarnessManager(global_path=tmp_path / "lumos")
        mgr.install(harness_src)
        mgr.use("h1")
        assert mgr.current() == "h1"

    def test_uninstall_active_resets(self, tmp_path):
        harness_src = _create_test_harness(tmp_path / "src", "h1")
        mgr = HarnessManager(global_path=tmp_path / "lumos")
        mgr.install(harness_src)
        mgr.use("h1")
        mgr.uninstall("h1")
        assert mgr.current() == "default"
        assert "h1" not in mgr.list_installed()

    def test_default_current(self, tmp_path):
        mgr = HarnessManager(global_path=tmp_path / "lumos")
        assert mgr.current() == "default"

    def test_project_level_overrides(self, tmp_path):
        harness_src = _create_test_harness(tmp_path / "src", "h1")
        global_path = tmp_path / "lumos"
        project = tmp_path / "project"
        (project / ".lumos").mkdir(parents=True)

        mgr = HarnessManager(global_path=global_path, project_root=project)
        mgr.install(harness_src)
        mgr.use("h1")

        # 项目级覆盖
        import yaml
        (project / ".lumos" / "config.yaml").write_text(
            yaml.safe_dump({"active_harness": "default"})
        )
        assert mgr.current() == "default"  # 项目级优先


# ============================================================================
# Harness Compose 测试
# ============================================================================

class TestHarnessCompose:
    def test_compose_basic(self, tmp_path):
        base = _create_test_harness(tmp_path / "base", "base-h")
        (base / "prompts" / "base.md").write_text("base prompt")

        mixin = _create_test_harness(tmp_path / "mixin", "mixin-h")
        (mixin / "prompts" / "mixin.md").write_text("mixin prompt")

        output = compose_harness(base, mixin, tmp_path / "output", "combined")
        assert (output / "HARNESS.yaml").is_file()
        assert (output / "prompts" / "base.md").is_file()
        assert (output / "prompts" / "mixin.md").is_file()

    def test_compose_mixin_overrides_config(self, tmp_path):
        base = _create_test_harness(tmp_path / "base", "base-h")
        (base / "config").mkdir()
        (base / "config" / "overrides.yaml").write_text("max_iterations: 30\n")

        mixin = _create_test_harness(tmp_path / "mixin", "mixin-h")
        (mixin / "config").mkdir()
        (mixin / "config" / "overrides.yaml").write_text("max_iterations: 50\n")

        output = compose_harness(base, mixin, tmp_path / "output", "combined")
        content = (output / "config" / "overrides.yaml").read_text()
        assert "50" in content  # mixin 覆盖


# ============================================================================
# MemorySynthesizer 测试
# ============================================================================

class TestMemorySynthesizer:
    def _write_learnings(self, path: Path, entries: list[dict]):
        with path.open("w") as f:
            for e in entries:
                f.write(json.dumps(e) + "\n")

    def test_recent_entries_full_text(self, tmp_path):
        now = datetime.now(timezone.utc)
        jsonl = tmp_path / "learnings.jsonl"
        self._write_learnings(jsonl, [
            {"ts": now.isoformat(), "type": "reflection",
             "lesson": "Context compression loses info", "context": "During SWE-bench", "source": "test"},
        ])
        output = tmp_path / "active_insights.md"
        synth = MemorySynthesizer()
        count = synth.synthesize(jsonl, output)
        assert count == 1
        content = output.read_text()
        assert "Recent" in content
        assert "Context compression loses info" in content
        assert "During SWE-bench" in content

    def test_medium_entries_grouped(self, tmp_path):
        now = datetime.now(timezone.utc)
        old = now - timedelta(days=20)
        jsonl = tmp_path / "learnings.jsonl"
        self._write_learnings(jsonl, [
            {"ts": old.isoformat(), "type": "reflection",
             "lesson": "Tool timeout causes issues", "context": "bash tool", "source": ""},
            {"ts": old.isoformat(), "type": "reflection",
             "lesson": "File tool needs retry", "context": "edit tool", "source": ""},
        ])
        output = tmp_path / "active_insights.md"
        synth = MemorySynthesizer()
        synth.synthesize(jsonl, output)
        content = output.read_text()
        assert "Medium" in content

    def test_empty_jsonl(self, tmp_path):
        jsonl = tmp_path / "learnings.jsonl"
        jsonl.write_text("")
        output = tmp_path / "active_insights.md"
        synth = MemorySynthesizer()
        count = synth.synthesize(jsonl, output)
        assert count == 0
        assert "No insights yet" in output.read_text()

    def test_missing_jsonl(self, tmp_path):
        output = tmp_path / "active_insights.md"
        synth = MemorySynthesizer()
        count = synth.synthesize(tmp_path / "nonexistent.jsonl", output)
        assert count == 0


# ============================================================================
# CLI 测试
# ============================================================================

class TestInitCmd:
    def test_init_python_project(self, tmp_path):
        (tmp_path / "pyproject.toml").write_text('[project]\nname = "test"')
        result = run_init(project_root=tmp_path)
        assert "Created" in result
        content = (tmp_path / "LUMOS.md").read_text()
        assert "python" in content.lower()

    def test_init_no_overwrite(self, tmp_path):
        (tmp_path / "LUMOS.md").write_text("existing")
        result = run_init(project_root=tmp_path)
        assert "Already exists" in result

    def test_init_force(self, tmp_path):
        (tmp_path / "LUMOS.md").write_text("existing")
        (tmp_path / "pyproject.toml").write_text('[project]\nname = "test"')
        result = run_init(project_root=tmp_path, force=True)
        assert "Created" in result


class TestSetupCmd:
    def test_setup_creates_files(self, tmp_path):
        result = run_setup(global_path=tmp_path / "lumos", user_name="Snape", timezone="Asia/Shanghai")
        assert "Created" in result
        ws = tmp_path / "lumos" / "workspace"
        assert (ws / "IDENTITY.md").is_file()
        assert (ws / "USER.md").is_file()
        assert (ws / "MEMORY.md").is_file()
        assert (ws / "TOOLS.md").is_file()
        assert (ws / "HEARTBEAT.md").is_file()
        assert "Snape" in (ws / "USER.md").read_text()

    def test_setup_no_overwrite(self, tmp_path):
        root = tmp_path / "lumos"
        ws = root / "workspace"
        ws.mkdir(parents=True)
        (ws / "IDENTITY.md").write_text("custom")
        (ws / "AGENT.md").write_text("custom")
        (ws / "USER.md").write_text("custom")
        (ws / "MEMORY.md").write_text("custom")
        (ws / "TOOLS.md").write_text("custom")
        (ws / "HEARTBEAT.md").write_text("custom")
        (ws / "memory").mkdir(exist_ok=True)
        (root / "packages").mkdir(exist_ok=True)
        (root / "config").mkdir(exist_ok=True)
        (root / "config" / "lumos.yaml").write_text("# existing config\n")
        result = run_setup(global_path=root)
        assert "already exists" in result.lower()
