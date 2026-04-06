# Lumos

> A self-evolving AI coding agent framework — observe, evaluate, optimize.

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![Platform](https://img.shields.io/badge/platform-Linux%20%7C%20macOS%20%7C%20Windows-lightgrey.svg)](https://github.com/)
[![Tests](https://img.shields.io/badge/tests-115%20passed-brightgreen.svg)](tests/)

## What is Lumos?

**Lumos** is a terminal AI coding agent with a built-in self-optimization loop. It doesn't just run LLM calls — it records every decision, evaluates the outcome, and tunes itself to get better over time.

The core thesis: **Agent framework value = self-optimization infrastructure.** Models get stronger every quarter, but the scaffolding around them — the harness — determines the actual capability ceiling. The same Claude Sonnet scores 20+ points differently on SWE-bench depending on the harness wrapping it.

Lumos makes that harness observable, evaluable, and optimizable.

```
Observe  →  Evaluate  →  Optimize  →  Distribute
   │            │            │             │
Trajectory   Evaluator    Optimizer    Harness
  Logger      (anchor)   (hill-climb)  Package
```

## Architecture

Lumos is built as a 7-layer stack. Each layer has a single responsibility:

```
┌─────────────────────────────────────────────────────────────┐
│ L7  Optimization    Evaluator · Optimizer · BenchmarkRunner │
├─────────────────────────────────────────────────────────────┤
│ L6  Trajectory      TrajectoryLogger · JSONL · Replay       │
├─────────────────────────────────────────────────────────────┤
│ L5  Interceptor     10 lifecycle points · Onion model       │
├─────────────────────────────────────────────────────────────┤
│ L4  Orchestration   agent_loop · Agent · ModeManager        │
├─────────────────────────────────────────────────────────────┤
│ L3  Capability      PromptComposer · WorkspaceLoader        │
│                     SkillManager · ToolRegistry             │
├─────────────────────────────────────────────────────────────┤
│ L2  Stream          StreamFn · EventStream · ModelRouter    │
├─────────────────────────────────────────────────────────────┤
│ L1  State           AgentState · Types · Queues             │
└─────────────────────────────────────────────────────────────┘
```

### Key Design Decisions

- **Pure-function `agent_loop`** — stateless core, injectable everything. Zero SDK dependency.
- **Interceptor = unified hooks + middleware** — one mechanism, 10 lifecycle points, onion model with `proceed()` chains. Replaces scattered hardcoded heuristics.
- **Trajectory as first-class data** — every turn, tool call, and error is recorded as structured JSONL. This is the fuel for evaluation and optimization.
- **Evaluator ≠ Agent** — evaluators are immutable anchors (Karpathy's `prepare.py` philosophy). They never ship inside a harness package. The judge and the player are always separate.
- **Single-active Harness** — like Python venv, one harness active at a time. No implicit stacking, no merge conflicts. `lumos harness use <name>` to switch.

## Harness Package

A Harness Package bundles optimized agent behavior into an installable unit:

```
my-harness/
├── HARNESS.yaml       # Manifest: metadata + provides + provenance
├── interceptors/      # Lifecycle interceptors (Python or YAML shell)
├── tools/             # LLM-callable tools (AgentTool)
├── skills/            # Activatable behavior patterns (SKILL.md)
├── prompts/           # Always-on prompt fragments
└── config/            # Config overrides (model params, loop behavior)
```

5 directories, each with exactly one responsibility:

| Directory | What | For whom | Not for |
|---|---|---|---|
| `interceptors/` | Code — intercept agent lifecycle | Harness runtime | Business logic tools |
| `tools/` | Code — exposed to LLM via tool_use | LLM | System interception |
| `skills/` | Prompt — activated on match | LLM | Always-on prompts |
| `prompts/` | Prompt — always injected | LLM | Activatable instructions |
| `config/` | Data — override defaults | Harness runtime | Any code |

```bash
lumos harness install ./my-harness    # Install (doesn't activate)
lumos harness use my-harness          # Activate (single-active)
lumos harness current                 # Show active
lumos harness list                    # List installed
lumos harness compose \               # Merge two into one
  --base swe-bench --mixin python-expert --name combined
```

## Interceptor System

10 lifecycle points, onion model execution:

```
before_agent → before_model → [wrap_model] → after_model
                                    ↓
             pre_tool_use → [wrap_tool] → post_tool_use
                                    ↓
                          on_stop → after_agent
                          on_error (any phase)
```

Each interceptor is a Python class with a `priority` (0 = outermost, 100 = innermost). The engine builds an onion chain — outer interceptors wrap inner ones, each calling `proceed()` to continue or short-circuiting to block/transform.

```python
from packages.server.interceptor.base import BaseInterceptor

class MyInterceptor(BaseInterceptor):
    name = "my-interceptor"
    priority = 50

    async def pre_tool_use(self, request, proceed):
        if request.tool_name == "bash" and "rm -rf" in str(request.arguments):
            return ToolResult(is_error=True, content="Blocked: dangerous command")
        return await proceed(request)
```

Built-in interceptors:
- **TrajectoryLogger** (priority=1) — records all events to JSONL
- **WriteRmLoopDetector** (priority=80) — detects write→delete anti-patterns

## Workspace & System Prompt

Lumos uses a layered workspace system for context injection:

```
~/.lumos/                        # Global workspace
├── IDENTITY.md                  # Agent identity (name, personality)
├── AGENT.md                     # Behavior rules
├── USER.md                      # User preferences
├── memory/                      # Memory system
│   ├── learnings.jsonl          # Append-only reflections
│   └── active_insights.md       # Synthesized insights (3-tier decay)
├── packages/                    # Installed harness packages
└── config/lumos.yaml            # Global config

<project>/                       # Project workspace
├── LUMOS.md                     # Project instructions (CLAUDE.md compatible)
└── .lumos/
    ├── config.yaml              # Project config
    └── memory/                  # Project-level memory
```

**PromptComposer** assembles the system prompt from 9 layers (L1 highest priority → L9 lowest). When over token budget, L8→L5 get compressed first; L1-L3 are never compressed:

| Layer | Source | Compressible |
|---|---|---|
| L1 Identity | IDENTITY.md | No |
| L2 Rules | AGENT.md + built-in | No |
| L3 User | USER.md | Light |
| L4 Project | LUMOS.md | Light |
| L5 Harness | Package prompts/ | Yes |
| L6 Skill | Active skill prompt | Yes |
| L7 Mode | BUILD/PLAN/REVIEW | Yes |
| L8 Memory | active_insights.md | Yes |
| L9 Runtime | cwd, git branch, etc. | Dynamic |

Compatible with `CLAUDE.md` — Lumos searches for `LUMOS.md` first, falls back to `CLAUDE.md`.

## Memory System

Dual-track memory inspired by [yoyo-evolve](https://github.com/yologdev/yoyo-evolve):

```
Track 1: Structured Trajectory (machine-readable)
  └─ TrajectoryLogger → JSONL → Evaluator → Optimizer

Track 2: Natural Language Learnings (human-readable)
  └─ Agent reflection → learnings.jsonl → MemorySynthesizer → active_insights.md
```

**MemorySynthesizer** applies 3-tier time decay:
- **Recent** (< 2 weeks) — full lesson + context
- **Medium** (2-8 weeks) — lessons grouped by theme
- **Foundational** (> 8 weeks) — core principles, no dates

The synthesized `active_insights.md` is injected into the system prompt at L8, giving the agent accumulated wisdom from past sessions.

## Evaluation & Optimization

The optimization loop is the core differentiator. Evaluators are immutable anchors — they never ship inside a harness. The judge and the player stay separate.

```
┌─────────────────────────────────────────────────────────┐
│  Harness Package (ships to users)                       │
│  interceptors/ tools/ skills/ prompts/ config/          │
└─────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────┐
│  Optimization Workspace (developer-local, never ships)  │
│  benchmarks/ evaluators/ trajectories/ scores.tsv .git/ │
└─────────────────────────────────────────────────────────┘
```

```bash
lumos optimize init --benchmark swe-bench-lite --harness ./my-harness
lumos optimize run --rounds 20     # Hill-climbing: tweak → benchmark → keep or revert
lumos optimize scores              # View score history
lumos optimize export              # Export best harness as installable package
```

Each round: tweak harness config → run benchmark → evaluate → score improves? `git commit` (keep). Score drops? `git revert`. All tracked in `scores.tsv`.

## Quick Start

### Install

```bash
pipx install git+https://github.com/SallyKAN/lumos.git
lumos --version
```

### Configure

```bash
lumos --config                     # Interactive setup

# Or set environment variables
export ANTHROPIC_API_KEY="..."     # Anthropic Claude
export OPENAI_API_KEY="..."        # OpenAI
export SILICONFLOW_API_KEY="..."   # SiliconFlow (budget-friendly)
```

Supported providers:

| Provider | Default Model |
|---|---|
| Anthropic | claude-sonnet-4-5 |
| OpenAI | gpt-4o |
| SiliconFlow | deepseek-ai/DeepSeek-V3 |
| ZhiPu | glm-4 |
| Custom | Any OpenAI-compatible endpoint |

### Use

```bash
lumos                              # Interactive mode
lumos "refactor this function"     # One-shot
lumos -p "analyze project"         # With prompt flag
```

### Initialize a Project

```bash
lumos init                         # Generate LUMOS.md (auto-detects language/framework)
lumos setup                        # First-time global setup (~/.lumos/)
```

## Project Structure

```
lumos/
├── packages/
│   ├── server/
│   │   ├── core/                  # agent_loop, LLM, Tool, Types
│   │   ├── agents/                # LumosAgent, ModeManager
│   │   ├── interceptor/           # InterceptorEngine, Protocol, BaseInterceptor
│   │   │   └── builtins/          # WriteRmLoopDetector
│   │   ├── trajectory/            # TrajectoryLogger, TrajectoryReplay
│   │   ├── capability/            # PromptComposer, WorkspaceLoader, ProjectScanner
│   │   ├── harness/               # HarnessLoader, HarnessManager, Compose
│   │   ├── memory/                # MemorySynthesizer
│   │   ├── evaluator/             # Evaluator ABC, EfficiencyEvaluator
│   │   │   └── builtins/
│   │   ├── optimization/          # OptimizationWorkspace, BenchmarkRunner, Optimizer
│   │   ├── tools/                 # 14+ built-in tools
│   │   ├── skills/                # Skill system (loader/matcher/executor)
│   │   └── api/                   # Web API (FastAPI + WebSocket)
│   └── cli/                       # TUI client + init/setup/harness commands
├── tests/                         # 115 tests
├── docs/                          # Architecture & design docs
└── pyproject.toml
```

## CLI Reference

```bash
# Modes
/mode build|plan|review

# Harness management
lumos harness install <path|git-url>
lumos harness use <name>
lumos harness current
lumos harness list
lumos harness compose --base <a> --mixin <b> --name <out>
lumos harness uninstall <name>

# Optimization
lumos optimize init --benchmark <name> --harness <path>
lumos optimize run --rounds <N>
lumos optimize scores
lumos optimize export --output <path>

# Project
lumos init                         # Generate LUMOS.md
lumos setup                        # Global workspace setup

# Skills
/skills list
/skills install <plugin>@<marketplace>
```

## Testing

```bash
pytest tests/ -v                   # 115 tests, ~0.5s
pytest --cov=packages/server --cov-report=html
```

## Roadmap

- [x] **Phase 1** — InterceptorEngine + TrajectoryLogger + agent_loop integration
- [x] **Phase 2** — Harness Package + Workspace + PromptComposer + Memory
- [x] **Phase 3** — Evaluation & Optimization (Evaluator + BenchmarkRunner + Optimizer)
- [ ] **Phase 4** — Ecosystem (Harness Registry, more interceptors/evaluators/benchmarks)

## License

MIT — see [LICENSE](LICENSE)

## Acknowledgments

- [Claude Code](https://docs.anthropic.com/en/docs/claude-code) — design inspiration
- [yoyo-evolve](https://github.com/yologdev/yoyo-evolve) — memory system patterns
- [OpenAI "The Scaffolding Matters"](https://arxiv.org/) — the thesis that harness determines capability ceiling

---

**Repository**: https://github.com/SallyKAN/lumos
