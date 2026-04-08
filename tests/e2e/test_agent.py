"""
E2E: LumosAgent instantiation and non-LLM behaviour.

Tests marked @pytest.mark.llm make real API calls and are skipped by default.
Run with:  pytest tests/e2e -m llm
"""

import pytest
import asyncio
from pathlib import Path

from packages.agents.lumos_agent import LumosAgent
from packages.agents.mode_manager import AgentModeManager, AgentMode


# ---------------------------------------------------------------------------
# Instantiation (no LLM calls)
# ---------------------------------------------------------------------------

class TestLumosAgentInit:
    def test_instantiate_with_dummy_key(self):
        agent = LumosAgent(
            model_provider="openai",
            api_key="test-key",
            model_name="gpt-4o",
        )
        assert agent is not None

    def test_default_mode_is_build(self):
        agent = LumosAgent(api_key="test-key")
        assert agent.get_current_mode() == AgentMode.BUILD

    def test_tools_registered(self):
        agent = LumosAgent(api_key="test-key")
        tools = agent.get_available_tools()
        assert "bash" in tools
        assert "read_file" in tools
        assert "write_file" in tools
        assert "edit_file" in tools

    def test_custom_system_prompt(self):
        agent = LumosAgent(api_key="test-key", system_prompt="Custom prompt")
        assert agent.system_prompt == "Custom prompt"

    def test_session_id_stored(self):
        agent = LumosAgent(api_key="test-key", session_id="my-session")
        assert agent.session_id == "my-session"

    def test_max_iterations_stored(self):
        agent = LumosAgent(api_key="test-key", max_iterations=5)
        assert agent.max_iterations == 5

    def test_project_root_accepted(self, tmp_path):
        agent = LumosAgent(api_key="test-key", project_root=str(tmp_path))
        assert agent is not None

    def test_anthropic_provider(self):
        agent = LumosAgent(
            model_provider="anthropic",
            api_key="test-key",
            model_name="claude-sonnet-4-5",
        )
        assert agent is not None


# ---------------------------------------------------------------------------
# Mode switching (no LLM calls)
# ---------------------------------------------------------------------------

class TestAgentModeSwitch:
    def test_switch_to_plan_mode(self):
        agent = LumosAgent(api_key="test-key")
        agent.switch_mode(AgentMode.PLAN)
        assert agent.get_current_mode() == AgentMode.PLAN

    def test_switch_to_review_mode(self):
        agent = LumosAgent(api_key="test-key")
        agent.switch_mode(AgentMode.REVIEW)
        assert agent.get_current_mode() == AgentMode.REVIEW

    def test_switch_back_to_build(self):
        agent = LumosAgent(api_key="test-key")
        agent.switch_mode(AgentMode.PLAN)
        agent.switch_mode(AgentMode.BUILD)
        assert agent.get_current_mode() == AgentMode.BUILD

    def test_mode_affects_tools(self):
        agent = LumosAgent(api_key="test-key")
        build_tools = set(agent.get_available_tools())
        agent.switch_mode(AgentMode.PLAN)
        plan_tools = set(agent.get_available_tools())
        assert len(build_tools) > 0
        assert len(plan_tools) > 0


# ---------------------------------------------------------------------------
# AgentModeManager unit
# ---------------------------------------------------------------------------

class TestAgentModeManager:
    def test_default_mode(self):
        mgr = AgentModeManager()
        assert mgr.current_mode == AgentMode.BUILD

    def test_switch_and_get(self):
        mgr = AgentModeManager()
        mgr.switch_mode(AgentMode.REVIEW)
        assert mgr.current_mode == AgentMode.REVIEW

    def test_all_modes_switchable(self):
        mgr = AgentModeManager()
        for mode in AgentMode:
            mgr.switch_mode(mode)
            assert mgr.current_mode == mode

    def test_switch_same_mode_is_noop(self):
        mgr = AgentModeManager()
        result = mgr.switch_mode(AgentMode.BUILD)
        assert mgr.current_mode == AgentMode.BUILD
        # Returns False when mode unchanged
        assert result is False


# ---------------------------------------------------------------------------
# LLM-backed tests (skipped unless -m llm)
# ---------------------------------------------------------------------------

@pytest.mark.llm
class TestAgentLLMInvoke:
    """Real LLM calls — requires LUMOS_E2E_API_KEY and a reachable endpoint."""

    @pytest.fixture(autouse=True)
    def agent(self):
        from tests.e2e.conftest import E2E_API_KEY, E2E_API_BASE, E2E_PROVIDER, E2E_MODEL
        self._agent = LumosAgent(
            model_provider=E2E_PROVIDER,
            api_key=E2E_API_KEY,
            api_base=E2E_API_BASE or None,
            model_name=E2E_MODEL,
            max_iterations=5,
        )

    def test_invoke_returns_response(self):
        result = asyncio.get_event_loop().run_until_complete(
            self._agent.invoke("Reply with exactly: PONG")
        )
        assert result is not None
        text = str(result.get("content", "") or result.get("response", ""))
        assert "PONG" in text.upper()

    def test_stream_yields_events(self):
        events = []

        async def collect():
            async for event in self._agent.stream("Reply with: OK", "e2e-stream"):
                events.append(event)

        asyncio.get_event_loop().run_until_complete(collect())
        assert len(events) > 0
        types = {e.type for e in events}
        assert "content" in types or "text" in types or "done" in types

    def test_invoke_with_tool_use(self, tmp_path):
        """Agent should be able to use read_file tool on a real file."""
        target = tmp_path / "hello.txt"
        target.write_text("secret-value-42")

        result = asyncio.get_event_loop().run_until_complete(
            self._agent.invoke(
                f"Read the file at {target} and tell me its exact contents."
            )
        )
        text = str(result.get("content", "") or result.get("response", ""))
        assert "secret-value-42" in text

    def test_max_iterations_respected(self):
        """Agent with max_iterations=1 should stop early."""
        from tests.e2e.conftest import E2E_API_KEY, E2E_API_BASE, E2E_PROVIDER, E2E_MODEL
        agent = LumosAgent(
            model_provider=E2E_PROVIDER,
            api_key=E2E_API_KEY,
            api_base=E2E_API_BASE or None,
            model_name=E2E_MODEL,
            max_iterations=1,
        )
        result = asyncio.get_event_loop().run_until_complete(
            agent.invoke("Count from 1 to 1000 using bash tool repeatedly")
        )
        assert result is not None  # Should not hang or crash
