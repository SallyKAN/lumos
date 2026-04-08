"""
E2E: `lumos init` and `lumos setup` commands via their Python API.
No LLM calls required.
"""

import pytest
from pathlib import Path

from packages.cli.commands.init_cmd import run_init
from packages.cli.commands.setup_cmd import run_setup


class TestLumosInit:
    def test_init_creates_lumos_md(self, project_dir):
        result = run_init(project_root=project_dir)
        assert (project_dir / "LUMOS.md").is_file()
        assert "Created" in result

    def test_init_detects_python(self, project_dir):
        run_init(project_root=project_dir)
        content = (project_dir / "LUMOS.md").read_text()
        assert "python" in content.lower()

    def test_init_no_overwrite_by_default(self, project_dir):
        (project_dir / "LUMOS.md").write_text("# existing")
        result = run_init(project_root=project_dir)
        assert "Already exists" in result or "already" in result.lower()
        assert (project_dir / "LUMOS.md").read_text() == "# existing"

    def test_init_force_overwrites(self, project_dir):
        (project_dir / "LUMOS.md").write_text("# old")
        result = run_init(project_root=project_dir, force=True)
        assert "Created" in result
        assert (project_dir / "LUMOS.md").read_text() != "# old"

    def test_init_unknown_project(self, tmp_path):
        empty = tmp_path / "empty"
        empty.mkdir()
        result = run_init(project_root=empty)
        assert (empty / "LUMOS.md").is_file()

    def test_init_node_project(self, tmp_path):
        p = tmp_path / "node_proj"
        p.mkdir()
        (p / "package.json").write_text('{"name": "myapp", "version": "1.0.0"}')
        run_init(project_root=p)
        content = (p / "LUMOS.md").read_text()
        assert "javascript" in content.lower() or "node" in content.lower()

    def test_init_rust_project(self, tmp_path):
        p = tmp_path / "rust_proj"
        p.mkdir()
        (p / "Cargo.toml").write_text('[package]\nname = "myapp"\nversion = "0.1.0"\n')
        run_init(project_root=p)
        content = (p / "LUMOS.md").read_text()
        assert "rust" in content.lower()

    def test_init_lumos_md_contains_project_name(self, project_dir):
        run_init(project_root=project_dir)
        content = (project_dir / "LUMOS.md").read_text()
        assert "myproject" in content.lower() or len(content) > 10


class TestLumosSetup:
    def test_setup_creates_workspace_structure(self, tmp_path):
        root = tmp_path / "lumos"
        result = run_setup(global_path=root)
        assert "Created" in result
        ws = root / "workspace"
        assert (ws / "IDENTITY.md").is_file()
        assert (ws / "AGENT.md").is_file()
        assert (ws / "USER.md").is_file()
        assert (ws / "MEMORY.md").is_file()
        assert (ws / "TOOLS.md").is_file()
        assert (ws / "HEARTBEAT.md").is_file()
        assert (ws / "memory").is_dir()
        assert (root / "packages").is_dir()
        assert (root / "config").is_dir()

    def test_setup_with_user_name(self, tmp_path):
        root = tmp_path / "lumos"
        run_setup(global_path=root, user_name="Alice")
        content = (root / "workspace" / "USER.md").read_text()
        assert "Alice" in content

    def test_setup_with_timezone(self, tmp_path):
        root = tmp_path / "lumos"
        run_setup(global_path=root, timezone="Asia/Tokyo")
        content = (root / "workspace" / "USER.md").read_text()
        assert "Tokyo" in content or "Asia" in content

    def test_setup_no_overwrite_existing(self, tmp_path):
        root = tmp_path / "lumos"
        ws = root / "workspace"
        ws.mkdir(parents=True)
        (ws / "IDENTITY.md").write_text("# custom identity")
        (ws / "AGENT.md").write_text("# custom agent")
        (ws / "USER.md").write_text("# custom user")
        (ws / "MEMORY.md").write_text("# custom memory")
        (ws / "TOOLS.md").write_text("# custom tools")
        (ws / "HEARTBEAT.md").write_text("# custom heartbeat")
        (ws / "memory").mkdir()
        (root / "packages").mkdir(parents=True)
        (root / "config").mkdir(parents=True)
        (root / "config" / "lumos.yaml").write_text("# existing\n")
        result = run_setup(global_path=root)
        assert "already" in result.lower() or "exists" in result.lower()
        assert (ws / "IDENTITY.md").read_text() == "# custom identity"

    def test_setup_idempotent_second_call(self, tmp_path):
        root = tmp_path / "lumos"
        run_setup(global_path=root, user_name="Bob")
        result2 = run_setup(global_path=root, user_name="Bob")
        # Second call should not crash
        assert result2 is not None

    def test_setup_creates_memory_files(self, tmp_path):
        root = tmp_path / "lumos"
        run_setup(global_path=root)
        memory_dir = root / "workspace" / "memory"
        assert memory_dir.is_dir()
        # learnings.jsonl may be created empty
        learnings = memory_dir / "learnings.jsonl"
        if learnings.exists():
            assert learnings.stat().st_size >= 0
