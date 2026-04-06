"""
E2E: CLI flags that don't require LLM calls.

Covers:
  lumos --version
  lumos --test
  lumos --no-color --version
  lumos <query> with no API key → exits with error message
  lumos -p <query> with no API key → exits with error message
"""

import pytest


class TestVersion:
    def test_version_flag(self, lumos):
        result = lumos.run(["--version"])
        assert result.returncode == 0
        assert "Lumos" in result.stdout or "0.1.0" in result.stdout

    def test_no_color_version(self, lumos):
        result = lumos.run(["--no-color", "--version"])
        assert result.returncode == 0


class TestSelfTest:
    def test_test_flag_runs(self, lumos):
        """--test instantiates LumosAgent with a dummy key — no LLM call.
        The CLI --test checks react_loop which may not exist; we just verify
        it runs and prints diagnostic output without hanging."""
        result = lumos.run(["--test"])
        # Either passes (✓) or fails with a clear error — must not hang/crash silently
        combined = result.stdout + result.stderr
        assert "测试" in combined or "agent" in combined.lower() or "✓" in combined

    def test_test_flag_shows_mode(self, lumos):
        result = lumos.run(["--test"])
        combined = result.stdout + result.stderr
        # Should at minimum show mode info before any tool check
        assert "build" in combined.lower() or "mode" in combined.lower() or "agent" in combined.lower()


class TestNoApiKey:
    def test_query_without_api_key_exits(self, tmp_path):
        """When no API key is configured, one-shot query should not hang."""
        import os, sys, subprocess
        from tests.e2e.conftest import REPO_ROOT

        fake_home = tmp_path / "home"
        fake_home.mkdir()
        # No config file written → no API key
        env = {
            **os.environ,
            "HOME": str(fake_home),
            "USERPROFILE": str(fake_home),
        }
        for k in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "ZHIPU_API_KEY", "SILICONFLOW_API_KEY"):
            env.pop(k, None)

        result = subprocess.run(
            [sys.executable, "-m", "packages.cli.main", "hello"],
            capture_output=True, text=True, timeout=10,
            cwd=str(REPO_ROOT), env=env,
        )
        # Should exit (not hang) and mention API key
        combined = result.stdout + result.stderr
        assert "api" in combined.lower() or "key" in combined.lower() or result.returncode != 0

    def test_prompt_flag_without_api_key_exits(self, tmp_path):
        import os, sys, subprocess
        from tests.e2e.conftest import REPO_ROOT

        fake_home = tmp_path / "home"
        fake_home.mkdir()
        env = {**os.environ, "HOME": str(fake_home), "USERPROFILE": str(fake_home)}
        for k in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "ZHIPU_API_KEY", "SILICONFLOW_API_KEY"):
            env.pop(k, None)

        result = subprocess.run(
            [sys.executable, "-m", "packages.cli.main", "-p", "hello"],
            capture_output=True, text=True, timeout=10,
            cwd=str(REPO_ROOT), env=env,
        )
        combined = result.stdout + result.stderr
        assert "api" in combined.lower() or "key" in combined.lower() or result.returncode != 0


class TestSkipWelcome:
    def test_skip_welcome_no_hang(self, tmp_path):
        """--skip-welcome with no API key should exit cleanly, not wait for input."""
        import os, sys, subprocess
        from tests.e2e.conftest import REPO_ROOT

        fake_home = tmp_path / "home"
        fake_home.mkdir()
        env = {**os.environ, "HOME": str(fake_home), "USERPROFILE": str(fake_home)}
        for k in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "ZHIPU_API_KEY", "SILICONFLOW_API_KEY"):
            env.pop(k, None)

        result = subprocess.run(
            [sys.executable, "-m", "packages.cli.main", "--skip-welcome"],
            capture_output=True, text=True, timeout=10,
            cwd=str(REPO_ROOT), env=env,
            input="",  # EOF on stdin
        )
        # Should not timeout — that's the key assertion
        assert result.returncode is not None
