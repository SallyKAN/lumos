"""
E2E: Harness management via Python API (HarnessManager).

These tests exercise the full install → use → list → uninstall lifecycle
against a real filesystem, using isolated tmp directories.
No LLM calls required.
"""

import pytest
import yaml
from pathlib import Path

from packages.server.harness.manager import HarnessManager
from packages.server.harness.loader import HarnessLoader
from packages.server.harness.compose import compose_harness


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_harness(path: Path, name: str, *, prompts: dict = None,
                 config: dict = None, interceptors: list = None,
                 skills: list = None) -> Path:
    """Create a harness directory with a proper HARNESS.yaml `provides:` section.

    HarnessLoader is manifest-driven: resources must be declared in `provides:`
    to be loaded. This helper writes both the files AND the manifest entries.
    """
    path.mkdir(parents=True, exist_ok=True)
    for d in ("prompts", "interceptors", "tools", "skills", "config"):
        (path / d).mkdir(exist_ok=True)

    provides: dict = {}

    if prompts:
        prompt_files = []
        for fname, content in prompts.items():
            (path / "prompts" / fname).write_text(content)
            prompt_files.append(fname)
        provides["prompts"] = {"system_append": prompt_files}

    if config:
        (path / "config" / "overrides.yaml").write_text(yaml.safe_dump(config))
        provides["config"] = {"path": "config/overrides.yaml"}

    if interceptors:
        interceptor_specs = []
        for fname, content in interceptors:
            (path / "interceptors" / fname).write_text(content)
            interceptor_specs.append(fname)
        provides["interceptors"] = interceptor_specs

    if skills:
        skill_names = []
        for sname in skills:
            skill_dir = path / "skills" / sname
            skill_dir.mkdir(exist_ok=True)
            (skill_dir / "SKILL.md").write_text(f"# {sname}\n")
            skill_names.append(sname)
        provides["skills"] = skill_names

    manifest = {"name": name, "version": "0.1.0", "provides": provides}
    (path / "HARNESS.yaml").write_text(yaml.safe_dump(manifest))
    return path


# ---------------------------------------------------------------------------
# Install / list / uninstall
# ---------------------------------------------------------------------------

class TestHarnessInstall:
    def test_install_from_local_dir(self, tmp_path, harness_dir):
        mgr = HarnessManager(global_path=tmp_path / "lumos")
        name = mgr.install(harness_dir)
        assert name == "test-harness"
        assert "test-harness" in mgr.list_installed()

    def test_install_creates_package_dir(self, tmp_path, harness_dir):
        mgr = HarnessManager(global_path=tmp_path / "lumos")
        mgr.install(harness_dir)
        installed = tmp_path / "lumos" / "packages" / "test-harness"
        assert installed.is_dir()
        assert (installed / "HARNESS.yaml").is_file()

    def test_install_copies_all_subdirs(self, tmp_path):
        src = make_harness(
            tmp_path / "src", "full-harness",
            prompts={"system.md": "be concise"},
            config={"max_iterations": 10},
        )
        mgr = HarnessManager(global_path=tmp_path / "lumos")
        mgr.install(src)
        pkg = tmp_path / "lumos" / "packages" / "full-harness"
        assert (pkg / "prompts" / "system.md").read_text() == "be concise"
        assert (pkg / "config" / "overrides.yaml").is_file()

    def test_install_missing_manifest_raises(self, tmp_path):
        bad = tmp_path / "bad-harness"
        bad.mkdir()
        mgr = HarnessManager(global_path=tmp_path / "lumos")
        with pytest.raises(Exception):
            mgr.install(bad)

    def test_list_empty_when_none_installed(self, tmp_path):
        mgr = HarnessManager(global_path=tmp_path / "lumos")
        assert mgr.list_installed() == []

    def test_list_multiple_installed(self, tmp_path):
        for name in ("alpha", "beta", "gamma"):
            src = make_harness(tmp_path / name, name)
            mgr = HarnessManager(global_path=tmp_path / "lumos")
            mgr.install(src)
        mgr = HarnessManager(global_path=tmp_path / "lumos")
        installed = mgr.list_installed()
        for name in ("alpha", "beta", "gamma"):
            assert name in installed

    def test_uninstall_removes_package(self, tmp_path, harness_dir):
        mgr = HarnessManager(global_path=tmp_path / "lumos")
        mgr.install(harness_dir)
        assert mgr.uninstall("test-harness") is True
        assert "test-harness" not in mgr.list_installed()

    def test_uninstall_nonexistent_returns_false(self, tmp_path):
        mgr = HarnessManager(global_path=tmp_path / "lumos")
        assert mgr.uninstall("ghost") is False

    def test_uninstall_active_resets_to_default(self, tmp_path, harness_dir):
        mgr = HarnessManager(global_path=tmp_path / "lumos")
        mgr.install(harness_dir)
        mgr.use("test-harness")
        mgr.uninstall("test-harness")
        assert mgr.current() == "default"


# ---------------------------------------------------------------------------
# Activate / current
# ---------------------------------------------------------------------------

class TestHarnessActivation:
    def test_default_current_before_any_use(self, tmp_path):
        mgr = HarnessManager(global_path=tmp_path / "lumos")
        assert mgr.current() == "default"

    def test_use_sets_current(self, tmp_path, harness_dir):
        mgr = HarnessManager(global_path=tmp_path / "lumos")
        mgr.install(harness_dir)
        mgr.use("test-harness")
        assert mgr.current() == "test-harness"

    def test_use_nonexistent_raises(self, tmp_path):
        mgr = HarnessManager(global_path=tmp_path / "lumos")
        with pytest.raises(Exception):
            mgr.use("ghost")

    def test_switch_between_harnesses(self, tmp_path):
        for name in ("h1", "h2"):
            src = make_harness(tmp_path / name, name)
            mgr = HarnessManager(global_path=tmp_path / "lumos")
            mgr.install(src)
        mgr = HarnessManager(global_path=tmp_path / "lumos")
        mgr.use("h1")
        assert mgr.current() == "h1"
        mgr.use("h2")
        assert mgr.current() == "h2"

    def test_project_config_overrides_global(self, tmp_path, harness_dir):
        project = tmp_path / "project"
        (project / ".lumos").mkdir(parents=True)
        global_path = tmp_path / "lumos"

        mgr = HarnessManager(global_path=global_path, project_root=project)
        mgr.install(harness_dir)
        mgr.use("test-harness")  # global active = test-harness

        # Project overrides to default
        (project / ".lumos" / "config.yaml").write_text(
            yaml.safe_dump({"active_harness": "default"})
        )
        assert mgr.current() == "default"


# ---------------------------------------------------------------------------
# HarnessLoader
# ---------------------------------------------------------------------------

class TestHarnessLoader:
    def test_load_name_and_version(self, harness_dir):
        loader = HarnessLoader(harness_dir)
        assert loader.name == "test-harness"
        assert loader.version == "0.1.0"

    def test_load_prompts(self, tmp_path):
        # prompts must be declared in provides.prompts.system_append
        src = make_harness(tmp_path / "h", "h",
                           prompts={"a.md": "prompt A", "b.md": "prompt B"})
        loader = HarnessLoader(src)
        combined = loader.load_prompts()
        assert "prompt A" in combined
        assert "prompt B" in combined

    def test_load_prompts_empty_when_not_declared(self, tmp_path):
        # Files exist but not declared in manifest → empty
        src = make_harness(tmp_path / "h", "h")
        (src / "prompts" / "undeclared.md").write_text("hidden")
        loader = HarnessLoader(src)
        assert loader.load_prompts() == ""

    def test_load_config_overrides(self, tmp_path):
        # config path must be declared in provides.config.path
        src = make_harness(tmp_path / "h", "h", config={"max_iterations": 42})
        loader = HarnessLoader(src)
        cfg = loader.load_config()
        assert cfg.get("max_iterations") == 42

    def test_load_config_empty_when_not_declared(self, tmp_path):
        src = make_harness(tmp_path / "h", "h")
        loader = HarnessLoader(src)
        assert loader.load_config() == {}

    def test_load_skill_dirs(self, tmp_path):
        # skills must be declared in provides.skills
        src = make_harness(tmp_path / "h", "h", skills=["my-skill"])
        loader = HarnessLoader(src)
        dirs = loader.load_skill_dirs()
        assert any(d.name == "my-skill" for d in dirs)

    def test_load_skill_dirs_empty_when_not_declared(self, tmp_path):
        src = make_harness(tmp_path / "h", "h")
        skill_dir = src / "skills" / "undeclared"
        skill_dir.mkdir()
        loader = HarnessLoader(src)
        assert loader.load_skill_dirs() == []

    def test_load_interceptors_empty(self, harness_dir):
        loader = HarnessLoader(harness_dir)
        interceptors = loader.load_interceptors()
        assert isinstance(interceptors, list)


# ---------------------------------------------------------------------------
# Compose
# ---------------------------------------------------------------------------

class TestHarnessCompose:
    def test_compose_merges_prompts(self, tmp_path):
        base = make_harness(tmp_path / "base", "base",
                            prompts={"base.md": "base prompt"})
        mixin = make_harness(tmp_path / "mixin", "mixin",
                             prompts={"mixin.md": "mixin prompt"})
        out = compose_harness(base, mixin, tmp_path / "out", "combined")
        assert (out / "prompts" / "base.md").read_text() == "base prompt"
        assert (out / "prompts" / "mixin.md").read_text() == "mixin prompt"

    def test_compose_mixin_config_wins(self, tmp_path):
        base = make_harness(tmp_path / "base", "base",
                            config={"max_iterations": 10, "temperature": 0.5})
        mixin = make_harness(tmp_path / "mixin", "mixin",
                             config={"max_iterations": 50})
        out = compose_harness(base, mixin, tmp_path / "out", "combined")
        cfg = yaml.safe_load((out / "config" / "overrides.yaml").read_text())
        assert cfg["max_iterations"] == 50

    def test_compose_manifest_has_correct_name(self, tmp_path):
        base = make_harness(tmp_path / "base", "base")
        mixin = make_harness(tmp_path / "mixin", "mixin")
        out = compose_harness(base, mixin, tmp_path / "out", "my-combined")
        manifest = yaml.safe_load((out / "HARNESS.yaml").read_text())
        assert manifest["name"] == "my-combined"

    def test_compose_output_is_installable(self, tmp_path):
        base = make_harness(tmp_path / "base", "base")
        mixin = make_harness(tmp_path / "mixin", "mixin")
        out = compose_harness(base, mixin, tmp_path / "out", "combined")

        mgr = HarnessManager(global_path=tmp_path / "lumos")
        mgr.install(out)
        assert "combined" in mgr.list_installed()

    def test_compose_existing_output_overwrites(self, tmp_path):
        # compose_harness silently overwrites existing output (shutil.rmtree + copytree)
        base = make_harness(tmp_path / "base", "base",
                            prompts={"p.md": "v1"})
        mixin = make_harness(tmp_path / "mixin", "mixin")
        out_dir = tmp_path / "out"
        compose_harness(base, mixin, out_dir, "combined")
        # Mutate base prompt and recompose — should reflect new content
        (base / "prompts" / "p.md").write_text("v2")
        # Re-declare in manifest
        import yaml as _yaml
        manifest = _yaml.safe_load((base / "HARNESS.yaml").read_text())
        manifest["provides"]["prompts"] = {"system_append": ["p.md"]}
        (base / "HARNESS.yaml").write_text(_yaml.safe_dump(manifest))
        out2 = compose_harness(base, mixin, out_dir, "combined")
        assert (out2 / "prompts" / "p.md").read_text() == "v2"
