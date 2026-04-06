"""
E2E test fixtures and helpers.

Environment variables that control e2e behaviour:
  LUMOS_E2E_API_KEY   — API key forwarded to the lumos process (default: "test-key")
  LUMOS_E2E_API_BASE  — API base URL (default: unset, uses provider default)
  LUMOS_E2E_PROVIDER  — provider name (default: "openai")
  LUMOS_E2E_MODEL     — model name   (default: "gpt-4o")
"""

import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest
import yaml


# ---------------------------------------------------------------------------
# Pytest markers
# ---------------------------------------------------------------------------

def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "llm: marks tests that make real LLM API calls (skipped by default)",
    )


def pytest_collection_modifyitems(config, items):
    if not config.getoption("-m", default=""):
        skip_llm = pytest.mark.skip(reason="LLM tests skipped by default; use -m llm to run")
        for item in items:
            if item.get_closest_marker("llm"):
                item.add_marker(skip_llm)


# ---------------------------------------------------------------------------
# E2E config from environment
# ---------------------------------------------------------------------------

E2E_API_KEY = os.environ.get("LUMOS_E2E_API_KEY", "test-key")
E2E_API_BASE = os.environ.get("LUMOS_E2E_API_BASE", "")
E2E_PROVIDER = os.environ.get("LUMOS_E2E_PROVIDER", "openai")
E2E_MODEL = os.environ.get("LUMOS_E2E_MODEL", "gpt-4o")

REPO_ROOT = Path(__file__).parent.parent.parent


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def lumos_home(tmp_path):
    """Isolated ~/.lumos directory for each test."""
    home = tmp_path / "lumos_home"
    home.mkdir()
    (home / "memory").mkdir()
    (home / "packages").mkdir()
    (home / "config").mkdir()
    return home


@pytest.fixture()
def lumos_config(lumos_home):
    """Write a minimal lumos config file and return its path."""
    cfg = {
        "api_key": E2E_API_KEY,
        "provider": E2E_PROVIDER,
        "model": E2E_MODEL,
    }
    if E2E_API_BASE:
        cfg["api_base_url"] = E2E_API_BASE

    config_dir = lumos_home / "config"
    config_file = lumos_home.parent / ".lumos" / "config.yaml"
    config_file.parent.mkdir(parents=True, exist_ok=True)
    config_file.write_text(yaml.safe_dump(cfg))
    return config_file


@pytest.fixture()
def project_dir(tmp_path):
    """A minimal Python project directory."""
    p = tmp_path / "myproject"
    p.mkdir()
    (p / "pyproject.toml").write_text('[project]\nname = "myproject"\nversion = "0.1.0"\n')
    (p / "main.py").write_text("def hello():\n    return 'hello'\n")
    return p


@pytest.fixture()
def harness_dir(tmp_path):
    """A minimal valid harness package directory."""
    h = tmp_path / "test-harness"
    h.mkdir()
    (h / "HARNESS.yaml").write_text(
        "name: test-harness\nversion: 0.1.0\nprovides: {}\n"
    )
    (h / "prompts").mkdir()
    (h / "prompts" / "system.md").write_text("Always be concise.\n")
    (h / "interceptors").mkdir()
    (h / "tools").mkdir()
    (h / "skills").mkdir()
    (h / "config").mkdir()
    (h / "config" / "overrides.yaml").write_text("max_iterations: 20\n")
    return h


# ---------------------------------------------------------------------------
# Process runner helper
# ---------------------------------------------------------------------------

class LumosProcess:
    """Thin wrapper around subprocess for running `lumos` commands."""

    def __init__(self, env: dict):
        self.env = env

    def run(self, args: list[str], *, cwd=None, timeout=30, input=None) -> subprocess.CompletedProcess:
        cmd = [sys.executable, "-m", "packages.cli.main"] + args
        return subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=str(cwd or REPO_ROOT),
            env=self.env,
            input=input,
        )

    def run_ok(self, args: list[str], **kwargs) -> subprocess.CompletedProcess:
        """Run and assert exit code 0."""
        result = self.run(args, **kwargs)
        assert result.returncode == 0, (
            f"lumos {args} exited {result.returncode}\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )
        return result


@pytest.fixture()
def lumos(tmp_path):
    """Return a LumosProcess with an isolated HOME and config."""
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    lumos_dir = fake_home / ".lumos"
    lumos_dir.mkdir()

    cfg = {
        "api_key": E2E_API_KEY,
        "provider": E2E_PROVIDER,
        "model": E2E_MODEL,
    }
    if E2E_API_BASE:
        cfg["api_base_url"] = E2E_API_BASE
    (lumos_dir / "config.yaml").write_text(yaml.safe_dump(cfg))

    env = {**os.environ, "HOME": str(fake_home), "USERPROFILE": str(fake_home)}
    # Remove any real API keys so tests don't accidentally hit real APIs
    for k in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "ZHIPU_API_KEY", "SILICONFLOW_API_KEY"):
        env.pop(k, None)
    env["LUMOS_E2E_API_KEY"] = E2E_API_KEY

    return LumosProcess(env=env)
