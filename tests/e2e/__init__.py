# E2E tests — run real lumos CLI processes, no mocking of LLM calls.
# Requires a valid API key in env (ANTHROPIC_API_KEY / OPENAI_API_KEY / etc.)
# or a mock server configured via LUMOS_E2E_API_BASE + LUMOS_E2E_API_KEY.
#
# Tests that make real LLM calls are marked @pytest.mark.llm and are skipped
# by default. Run them with:  pytest tests/e2e -m llm
#
# All other e2e tests (CLI flags, harness management, config, init/setup)
# run without any API key and complete in < 5 s.
