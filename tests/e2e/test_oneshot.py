"""
E2E: One-shot `lumos <query>` and `lumos -p <query>` via subprocess.

Non-LLM tests verify process exit behaviour, argument parsing, and
slash-command routing. LLM tests verify real agent output.
"""

import os
import sys
import subprocess
import pytest
from pathlib import Path

from tests.e2e.conftest import REPO_ROOT, E2E_API_KEY, E2E_API_BASE, E2E_PROVIDER, E2E_MODEL


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def run_lumos(args, *, env=None, cwd=None, timeout=30, input=None):
    cmd = [sys.executable, "-m", "packages.cli.main"] + args
    return subprocess.run(
        cmd,
        capture_output=True, text=True,
        timeout=timeout,
        cwd=str(cwd or REPO_ROOT),
        env=env or os.environ.copy(),
        input=input,
    )


def make_env(tmp_path, *, api_key=E2E_API_KEY, provider=E2E_PROVIDER,
             model=E2E_MODEL, api_base=E2E_API_BASE):
    import yaml
    fake_home = tmp_path / "home"
    fake_home.mkdir(exist_ok=True)
    lumos_dir = fake_home / ".lumos"
    lumos_dir.mkdir(exist_ok=True)
    cfg = {"api_key": api_key, "provider": provider, "model": model}
    if api_base:
        cfg["api_base_url"] = api_base
    (lumos_dir / "config.yaml").write_text(yaml.safe_dump(cfg))
    env = {**os.environ, "HOME": str(fake_home), "USERPROFILE": str(fake_home)}
    for k in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "ZHIPU_API_KEY", "SILICONFLOW_API_KEY"):
        env.pop(k, None)
    return env


# ---------------------------------------------------------------------------
# Argument parsing (no LLM)
# ---------------------------------------------------------------------------

class TestOneShotArgParsing:
    def test_version_exits_zero(self, tmp_path):
        result = run_lumos(["--version"], env=make_env(tmp_path))
        assert result.returncode == 0
        assert "0.1.0" in result.stdout or "Lumos" in result.stdout

    def test_test_flag_exits_zero(self, tmp_path):
        result = run_lumos(["--test"], env=make_env(tmp_path))
        assert result.returncode == 0

    def test_no_color_flag_accepted(self, tmp_path):
        result = run_lumos(["--no-color", "--version"], env=make_env(tmp_path))
        assert result.returncode == 0

    def test_positional_query_accepted(self, tmp_path):
        """Positional query with a configured key should not crash at arg-parse."""
        # Will fail at LLM call with a fake key — that's fine, we just check it
        # doesn't crash with "unrecognized arguments" or similar.
        result = run_lumos(["hello world"], env=make_env(tmp_path), timeout=15)
        combined = result.stdout + result.stderr
        assert "unrecognized" not in combined.lower()
        assert "usage:" not in combined.lower()

    def test_prompt_flag_accepted(self, tmp_path):
        result = run_lumos(["-p", "hello"], env=make_env(tmp_path), timeout=15)
        combined = result.stdout + result.stderr
        assert "unrecognized" not in combined.lower()

    def test_skip_welcome_flag_accepted(self, tmp_path):
        result = run_lumos(["--skip-welcome"], env=make_env(tmp_path),
                           timeout=10, input="")
        assert result.returncode is not None  # didn't hang


# ---------------------------------------------------------------------------
# Config flag (no LLM)
# ---------------------------------------------------------------------------

class TestConfigFlag:
    def test_config_shows_current_key(self, tmp_path):
        env = make_env(tmp_path, api_key="sk-test1234")
        result = run_lumos(["--config"], env=env, timeout=10, input="n\n")
        combined = result.stdout + result.stderr
        assert "1234" in combined or "configured" in combined.lower()

    def test_config_no_key_shows_setup_prompt(self, tmp_path):
        fake_home = tmp_path / "home"
        fake_home.mkdir()
        (fake_home / ".lumos").mkdir()
        env = {**os.environ, "HOME": str(fake_home), "USERPROFILE": str(fake_home)}
        for k in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "ZHIPU_API_KEY", "SILICONFLOW_API_KEY"):
            env.pop(k, None)
        result = run_lumos(["--config"], env=env, timeout=10, input="\n")
        combined = result.stdout + result.stderr
        assert "api" in combined.lower() or "key" in combined.lower()


# ---------------------------------------------------------------------------
# LLM-backed one-shot tests
# ---------------------------------------------------------------------------

@pytest.mark.llm
class TestOneShotLLM:
    def test_positional_query_returns_output(self, tmp_path):
        env = make_env(tmp_path)
        result = run_lumos(["Reply with exactly: HELLO"], env=env, timeout=60)
        assert result.returncode == 0
        assert "HELLO" in result.stdout.upper()

    def test_prompt_flag_returns_output(self, tmp_path):
        env = make_env(tmp_path)
        result = run_lumos(["-p", "Reply with exactly: WORLD"], env=env, timeout=60)
        assert result.returncode == 0
        assert "WORLD" in result.stdout.upper()

    def test_no_color_strips_ansi(self, tmp_path):
        env = make_env(tmp_path)
        result = run_lumos(["--no-color", "Say: PLAIN"], env=env, timeout=60)
        assert result.returncode == 0
        assert "\033[" not in result.stdout

    def test_tool_use_bash(self, tmp_path):
        env = make_env(tmp_path)
        result = run_lumos(
            ["-p", "Run `echo lumos-e2e-marker` in bash and show me the output"],
            env=env, timeout=60, cwd=tmp_path,
        )
        assert result.returncode == 0
        assert "lumos-e2e-marker" in result.stdout

    def test_tool_use_write_and_read(self, tmp_path):
        env = make_env(tmp_path)
        target = tmp_path / "out.txt"
        result = run_lumos(
            ["-p", f"Write the text 'e2e-content' to {target}, then read it back and confirm."],
            env=env, timeout=90, cwd=tmp_path,
        )
        assert result.returncode == 0
        assert target.exists()
        assert "e2e-content" in target.read_text()

    def test_slash_mode_build(self, tmp_path):
        env = make_env(tmp_path)
        result = run_lumos(["/mode build", "Say: MODE_OK"], env=env, timeout=60)
        assert result.returncode == 0

    def test_multiline_output(self, tmp_path):
        env = make_env(tmp_path)
        result = run_lumos(
            ["-p", "List the numbers 1 through 5, one per line"],
            env=env, timeout=60,
        )
        assert result.returncode == 0
        lines = [l for l in result.stdout.splitlines() if l.strip().isdigit()]
        assert len(lines) >= 3
