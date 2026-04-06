# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Install for development
pip install -e ".[dev]"

# Run tests
pytest tests/ -v
pytest tests/ -v -k "test_name"          # single test
pytest --cov=packages/server --cov-report=html

# Lint / format / type-check
black packages/ tests/
flake8 packages/ tests/
mypy packages/
```

## Architecture

Lumos is a self-optimizing AI coding agent framework with a 7-layer stack:

```
L7  Optimization   packages/server/evaluator/ + optimization/
L6  Trajectory     packages/server/trajectory/
L5  Interceptor    packages/server/interceptor/
L4  Orchestration  packages/server/agents/  (agent_loop, ModeManager)
L3  Capability     packages/server/capability/  (PromptComposer, WorkspaceLoader)
L2  Stream         packages/server/core/  (StreamFn, ModelRouter)
L1  State          packages/server/core/  (AgentState, Types)
```

Entry point: `packages/cli/main.py` → `packages/server/agents/` → `agent_loop` in `packages/server/core/`.

### Key design invariants

- `agent_loop` is a **pure function** — stateless, injectable, zero SDK dependency. Don't add side effects to it directly; use interceptors instead.
- **Interceptors** are the single extension point for lifecycle hooks. 10 lifecycle points, onion model with `proceed()` chains. Priority 0 = outermost, 100 = innermost. Built-ins: `TrajectoryLogger` (priority=1), `WriteRmLoopDetector` (priority=80).
- **Evaluators never ship in harness packages** — the judge and the player must stay separate. Evaluators live in `packages/server/evaluator/`, harness packages live in `~/.lumos/packages/`.
- **Single-active harness** — like Python venv. `lumos harness use <name>` to switch.

### Harness Package structure

```
my-harness/
├── HARNESS.yaml       # manifest
├── interceptors/      # lifecycle interceptors (Python or YAML shell)
├── tools/             # LLM-callable tools
├── skills/            # activatable prompt patterns
├── prompts/           # always-on prompt fragments
└── config/            # config overrides
```

### PromptComposer layers (L1 = highest priority, never compressed)

| Layer | Source | Compressible |
|---|---|---|
| L1 Identity | `~/.lumos/IDENTITY.md` | No |
| L2 Rules | `~/.lumos/AGENT.md` | No |
| L3 User | `~/.lumos/USER.md` | Light |
| L4 Project | `LUMOS.md` (falls back to `CLAUDE.md`) | Light |
| L5–L8 | Harness prompts, skill, mode, memory | Yes |
| L9 Runtime | cwd, git branch | Dynamic |

### Writing a new interceptor

```python
from packages.server.interceptor.base import BaseInterceptor

class MyInterceptor(BaseInterceptor):
    name = "my-interceptor"
    priority = 50  # 0=outermost, 100=innermost

    async def pre_tool_use(self, request, proceed):
        # short-circuit or transform, then call proceed
        return await proceed(request)
```

Register it in the harness `interceptors/` directory or inject it directly into `InterceptorEngine`.
