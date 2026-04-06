# Lumos

[English](#what-is-lumos) | [中文](#lumos-是什么)

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

---

# 中文文档

## Lumos 是什么？

**Lumos** 是一个内置自优化闭环的终端 AI 编程 Agent 框架。它不只是调用 LLM——它记录每一个决策，评估结果，然后自动调优让自己越来越好。

核心论点：**Agent 框架的价值 = 自优化的基础设施。** 模型每个季度都在变强，但包裹模型的 scaffold（harness）决定了实际能力上限。同一个 Claude Sonnet 在 SWE-bench 上因 harness 不同，分数可差 20+ 个百分点。

Lumos 让这个 harness 变得可观测、可评估、可调优。

```
观测  →  评估  →  优化  →  分发
 │        │        │        │
行为     评估器   优化器   Harness
轨迹    (锚点)  (爬山法)   Package
```

## 架构

7 层分层架构，每层职责单一：

```
┌─────────────────────────────────────────────────────────────┐
│ L7  优化层        Evaluator · Optimizer · BenchmarkRunner   │
├─────────────────────────────────────────────────────────────┤
│ L6  轨迹层        TrajectoryLogger · JSONL · Replay         │
├─────────────────────────────────────────────────────────────┤
│ L5  拦截层        10 个生命周期点 · 洋葱模型                │
├─────────────────────────────────────────────────────────────┤
│ L4  编排层        agent_loop · Agent · ModeManager          │
├─────────────────────────────────────────────────────────────┤
│ L3  能力层        PromptComposer · WorkspaceLoader          │
│                   SkillManager · ToolRegistry               │
├─────────────────────────────────────────────────────────────┤
│ L2  流式层        StreamFn · EventStream · ModelRouter      │
├─────────────────────────────────────────────────────────────┤
│ L1  状态层        AgentState · Types · Queues               │
└─────────────────────────────────────────────────────────────┘
```

### 核心设计决策

- **纯函数 `agent_loop`** — 无状态核心，一切可注入，零 SDK 依赖
- **Interceptor = 统一的 hooks + middleware** — 一套机制，10 个生命周期点，洋葱模型 `proceed()` 调用链。替代散落各处的硬编码 heuristic
- **Trajectory 是一等公民** — 每个 turn、tool call、error 都记录为结构化 JSONL，这是评估和优化的燃料
- **Evaluator ≠ Agent** — 评估器是不可变锚点（Karpathy 的 `prepare.py` 哲学），永远不打包进 harness。裁判和选手必须分离
- **单活跃 Harness** — 类比 Python venv，同一时刻只有一个 harness 生效。`lumos harness use <name>` 切换

## Harness Package

Harness Package 把优化后的 agent 行为打包成可安装的单元：

```
my-harness/
├── HARNESS.yaml       # 清单：元数据 + 资源声明 + 优化来源
├── interceptors/      # 生命周期拦截器（Python 或 YAML shell 简写）
├── tools/             # LLM 可调用的工具（AgentTool）
├── skills/            # 可激活的行为模式（SKILL.md）
├── prompts/           # 始终生效的 prompt 片段
└── config/            # 配置覆盖（模型参数、循环行为等）
```

5 个目录，每个职责清晰不重叠：

| 目录 | 本质 | 给谁用 | 不应包含 |
|---|---|---|---|
| `interceptors/` | 代码 — 拦截 agent 生命周期 | Harness 运行时 | 业务逻辑工具 |
| `tools/` | 代码 — 暴露给 LLM 调用 | LLM（tool_use） | 系统拦截逻辑 |
| `skills/` | Prompt — 匹配时激活 | LLM | 始终生效的 prompt |
| `prompts/` | Prompt — 始终注入 | LLM | 可激活的指令 |
| `config/` | 数据 — 覆盖默认配置 | Harness 运行时 | 任何代码 |

```bash
lumos harness install ./my-harness    # 安装（不激活）
lumos harness use my-harness          # 激活（单活跃）
lumos harness current                 # 查看当前
lumos harness list                    # 列出已安装
lumos harness compose \               # 组合两个为一个
  --base swe-bench --mixin python-expert --name combined
```

## 拦截器系统

10 个生命周期点，洋葱模型执行：

```
before_agent → before_model → [wrap_model] → after_model
                                    ↓
             pre_tool_use → [wrap_tool] → post_tool_use
                                    ↓
                          on_stop → after_agent
                          on_error（任意阶段）
```

每个拦截器是一个 Python 类，带 `priority`（0 = 最外层，100 = 最内层）。引擎构建洋葱链——外层拦截器包裹内层，每个调用 `proceed()` 继续或短路来阻断/变换。

```python
from packages.server.interceptor.base import BaseInterceptor

class MyInterceptor(BaseInterceptor):
    name = "my-interceptor"
    priority = 50

    async def pre_tool_use(self, request, proceed):
        if request.tool_name == "bash" and "rm -rf" in str(request.arguments):
            return ToolResult(is_error=True, content="已阻断：危险命令")
        return await proceed(request)
```

内置拦截器：
- **TrajectoryLogger**（priority=1）— 记录所有事件到 JSONL
- **WriteRmLoopDetector**（priority=80）— 检测 write→delete 反模式

## Workspace 与 System Prompt

分层 Workspace 系统，自动注入上下文：

```
~/.lumos/                        # 全局 workspace
├── IDENTITY.md                  # Agent 身份（名字、人格）
├── AGENT.md                     # 行为规范
├── USER.md                      # 用户偏好
├── memory/                      # 记忆系统
│   ├── learnings.jsonl          # 只追加的反思归档
│   └── active_insights.md       # 合成的活跃洞察（三层衰减）
├── packages/                    # 已安装的 harness packages
└── config/lumos.yaml            # 全局配置

<项目>/                           # 项目 workspace
├── LUMOS.md                     # 项目指令（兼容 CLAUDE.md）
└── .lumos/
    ├── config.yaml              # 项目配置
    └── memory/                  # 项目级记忆
```

**PromptComposer** 从 9 层组装 system prompt（L1 优先级最高 → L9 最低）。超出 token 预算时，L8→L5 先被压缩；L1-L3 永不压缩：

| 层级 | 来源 | 可压缩 |
|---|---|---|
| L1 身份 | IDENTITY.md | 否 |
| L2 规范 | AGENT.md + 内置规则 | 否 |
| L3 用户 | USER.md | 轻度 |
| L4 项目 | LUMOS.md | 轻度 |
| L5 Harness | Package prompts/ | 是 |
| L6 Skill | 活跃 skill prompt | 是 |
| L7 模式 | BUILD/PLAN/REVIEW | 是 |
| L8 记忆 | active_insights.md | 是 |
| L9 运行时 | cwd, git branch 等 | 动态 |

兼容 `CLAUDE.md` — 优先搜索 `LUMOS.md`，未找到时回退到 `CLAUDE.md`。

## 记忆系统

双轨记忆，灵感来自 [yoyo-evolve](https://github.com/yologdev/yoyo-evolve)：

```
轨道 1: 结构化 Trajectory（机器可分析）
  └─ TrajectoryLogger → JSONL → Evaluator → Optimizer

轨道 2: 自然语言 Learnings（人类可阅读）
  └─ Agent 反思 → learnings.jsonl → MemorySynthesizer → active_insights.md
```

**MemorySynthesizer** 三层时间衰减：
- **近期**（< 2 周）— 完整 lesson + context
- **中期**（2-8 周）— 按主题聚合的 lesson 精华
- **基础**（> 8 周）— 核心原则，不带日期

合成的 `active_insights.md` 通过 L8 层注入 system prompt，让 agent 拥有跨 session 的累积智慧。

## 评估与优化

优化闭环是核心差异化能力。评估器是不可变锚点——永远不打包进 harness。裁判和选手始终分离。

```
┌─────────────────────────────────────────────────────────┐
│  Harness Package（分发给用户）                           │
│  interceptors/ tools/ skills/ prompts/ config/          │
└─────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────┐
│  Optimization Workspace（开发者本地，不分发）             │
│  benchmarks/ evaluators/ trajectories/ scores.tsv .git/ │
└─────────────────────────────────────────────────────────┘
```

```bash
lumos optimize init --benchmark swe-bench-lite --harness ./my-harness
lumos optimize run --rounds 20     # 爬山法：微调 → benchmark → 保留或回退
lumos optimize scores              # 查看分数历史
lumos optimize export              # 导出最优 harness 为可安装包
```

每轮：微调 harness 配置 → 跑 benchmark → 评估 → 分数提升？`git commit`（保留）。分数下降？`git revert`（回退）。全部记录在 `scores.tsv`。

## 快速开始

### 安装

```bash
pipx install git+https://github.com/SallyKAN/lumos.git
lumos --version
```

### 配置

```bash
lumos --config                     # 交互式配置

# 或设置环境变量
export ANTHROPIC_API_KEY="..."     # Anthropic Claude
export OPENAI_API_KEY="..."        # OpenAI
export SILICONFLOW_API_KEY="..."   # 硅基流动（超低价）
```

支持的提供商：

| 提供商 | 默认模型 |
|---|---|
| Anthropic | claude-sonnet-4-5 |
| OpenAI | gpt-4o |
| 硅基流动 | deepseek-ai/DeepSeek-V3 |
| 智谱 | glm-4 |
| 自定义 | 任何 OpenAI 兼容接口 |

### 使用

```bash
lumos                              # 交互式模式
lumos "重构这个函数"                # 一次性
lumos -p "分析项目结构"             # 带 prompt 参数
```

### 初始化项目

```bash
lumos init                         # 生成 LUMOS.md（自动检测语言/框架）
lumos setup                        # 首次全局初始化（~/.lumos/）
```

## 路线图

- [x] **Phase 1** — InterceptorEngine + TrajectoryLogger + agent_loop 改造
- [x] **Phase 2** — Harness Package + Workspace + PromptComposer + 记忆系统
- [x] **Phase 3** — 评估与优化（Evaluator + BenchmarkRunner + Optimizer）
- [ ] **Phase 4** — 生态（Harness Registry、更多拦截器/评估器/Benchmark）

## 致谢

- [Claude Code](https://docs.anthropic.com/en/docs/claude-code) — 设计灵感
- [yoyo-evolve](https://github.com/yologdev/yoyo-evolve) — 记忆系统模式
- [OpenAI "The Scaffolding Matters"](https://arxiv.org/) — harness 决定能力上限的核心论点
