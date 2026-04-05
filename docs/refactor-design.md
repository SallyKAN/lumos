# Lumos 重构设计文档

> **Harness-Optimize Native Architecture**
>
> 核心论点：Agent 框架的存在价值 = 自优化的基础设施。
> 框架不是帮你"编排 agent"，而是让 agent 能够被观测、被评估、被系统性优化。
>
> 版本：v2.1-draft
> 日期：2026-04-04（更新 Workspace & System Prompt 系统）

---

## 目录

1. [概述与动机](#1-概述与动机)
2. [现有架构概览与 Gap 分析](#2-现有架构概览与-gap-分析)
3. [目标架构（7 层分层图）](#3-目标架构7-层分层图)
4. [Interceptor 系统详细设计](#4-interceptor-系统详细设计)
5. [Trajectory Logger 设计](#5-trajectory-logger-设计)
6. [Harness Package 设计](#6-harness-package-设计)
7. [Evaluation & Optimization 设计](#7-evaluation--optimization-设计)
8. [现有模块迁移方案](#8-现有模块迁移方案)
9. [新增模块清单与依赖图](#9-新增模块清单与依赖图)
10. [分阶段实施路线图](#10-分阶段实施路线图)
11. [Workspace & System Prompt 系统](#11-workspace--system-prompt-系统)
12. [记忆系统设计](#12-记忆系统设计)

---

## 1. 概述与动机

### 1.1 背景

Lumos 是一个 Python 终端 AI 编程助手。当前架构已经具备：

- **Pi Agent 风格的纯函数 `agent_loop` + 有状态 `Agent` 壳** — 职责分离清晰
- **双层工具抽象** — `BaseTool`（旧）+ `AgentTool`（新），`wrap_legacy_tool` 桥接
- **Skill 系统** — SKILL.md 发现 → 匹配 → 注入 prompt → 过滤 tools
- **三模式系统** — BUILD / PLAN / REVIEW，`ModeManager` 控制权限
- **双模型路由** — 主模型 + 小模型用于子 agent
- **EventStream 异步事件流** + **StreamFn Protocol**（可替换的 LLM 调用层）
- **子 Agent spawn** — `TaskTool` 创建新 `LumosAgent` 实例

这些构成了一个可用的编程助手，但它缺少一个关键能力：**系统性的自优化闭环**。

### 1.2 核心洞见

> 模型越来越强，30 行代码就能搭一个 agent。框架如果只是帮你"编排 LLM 调用"，
> 那确实越来越没必要。但如果框架的定位是 **"自优化的锚点"**——让 agent 的行为
> 可以被观测、被评估、被系统性调优——那框架就是绝对必要的基础设施。

OpenAI 2025 年论文 *"The Scaffolding Matters"* 用实验证明：弱模型 + 优秀 scaffold > 强模型 + 朴素 scaffold。同一个 Claude 3.5 Sonnet 在 SWE-bench 上因 scaffold 不同，分数可差 20+ 个百分点。Harness 不是可选附加层，它决定 agent 的能力上限。

### 1.3 重构目标

将 Lumos 从一个"可用的编程助手"演进为一个 **Harness-Optimize Native** 的 Agent 框架：

1. **可观测** — 每个决策点都有完整的行为轨迹记录
2. **可评估** — 独立于 agent 的评估函数衡量表现
3. **可调优** — Interceptor 机制让行为的每个切面都可以被拦截和修改
4. **可分发** — Harness Package 把优化后的配置打包成可安装的产品

---

## 2. 现有架构概览与 Gap 分析

### 2.1 现有架构模块图

```
┌──────────────────────────────────────────────────────────┐
│                     LumosAgent                            │
│  (system_prompt, mode_manager, skill_manager, tools)     │
│                                                           │
│  ┌─────────────────────────────────────────────────────┐ │
│  │  Core Agent (有状态壳)                                │ │
│  │  state / abort / queues / subscribe                   │ │
│  │                                                       │ │
│  │  ┌───────────────────────────────────────────────┐   │ │
│  │  │  agent_loop (纯函数)                           │   │ │
│  │  │  外层: follow-up 驱动                          │   │ │
│  │  │  内层: tool call + steering                    │   │ │
│  │  │                                                │   │ │
│  │  │  StreamFn ──→ LLM API                         │   │ │
│  │  │  AgentTool ──→ Tool 执行                      │   │ │
│  │  │  EventStream ──→ 事件推送                     │   │ │
│  │  └───────────────────────────────────────────────┘   │ │
│  └─────────────────────────────────────────────────────┘ │
│                                                           │
│  ModeManager ─── BUILD / PLAN / REVIEW                   │
│  SkillManager ── load / match / activate / filter        │
│  ModelRouter ─── main model / small model                │
│  TaskTool ────── spawn sub-agent                         │
└──────────────────────────────────────────────────────────┘
```

### 2.2 Gap 分析

| 维度 | 现状 | 缺失 | 影响 |
|---|---|---|---|
| **ReAct Loop** | ✅ 双层循环（outer follow-up, inner tool call） | 循环行为不可被外部观测和调优 | 无法知道 agent 在哪个 turn 走了弯路 |
| **Tool System** | ✅ `AgentTool` + `BaseTool`，`wrap_legacy_tool` 桥接 | Tool 使用模式没有被记录和分析 | 不知道哪些工具调用模式是反模式 |
| **Skill System** | ✅ SKILL.md 可插拔 | Skill 效果没有被评估 | 不知道哪个 skill 实际提升了完成率 |
| **Loop Detection** | ✅ write-rm 反模式检测 | 硬编码 heuristic，不是学习来的 | 只能检测已知模式，无法适应新模式 |
| **Mode System** | ✅ BUILD/PLAN/REVIEW | 模式切换策略固定 | 无法根据任务类型自动选择最优模式 |
| **Trajectory Logging** | ⚠️ 有 config 占位但未实现 | 自优化的数据基础缺失 | 没有数据就没有评估，没有评估就没有优化 |
| **Evaluation/Reward** | ❌ 完全缺失 | 无法衡量 agent 表现 | "感觉变好了"不是工程 |
| **Optimization Loop** | ❌ 完全缺失 | 没有闭环 | 手动调参不可复现 |
| **Interceptor 机制** | ❌ 完全缺失 | 没有统一的生命周期拦截 | 横切关注点散落在各处，难以组合 |
| **Harness Package** | ❌ 完全缺失 | 优化结果无法分发 | 每个人都从零开始调参 |

### 2.3 现有代码的优势（保留并增强）

1. **纯函数 `agent_loop`** — 无副作用、可测试、可替换。这是 Pi Agent 的核心设计，必须保留。
2. **`StreamFn` Protocol** — LLM 调用层完全可注入，支持 Anthropic/OpenAI，扩展新 provider 只需实现协议。
3. **`EventStream`** — 异步事件流已经是观测的基础，Trajectory Logger 可以直接挂在上面。
4. **`AgentTool` 组合模式** — 不要求继承，传入 `execute_fn` 即可，符合 Composition over Inheritance。
5. **`wrap_legacy_tool` 桥接** — 渐进迁移的范例，v2 的所有改造都应遵循这个模式。

---

## 3. 目标架构（7 层分层图）

```
┌─────────────────────────────────────────────────────────────────────┐
│                      LUMOS V2 ARCHITECTURE                          │
│                                                                     │
│  ┌───────────────────────────────────────────────────────────────┐ │
│  │ L7: OPTIMIZATION LAYER  (自优化引擎 — 不分发，本地独立)       │ │
│  │   • Evaluator — 不可变评估锚点，独立于 agent                  │ │
│  │   • Optimizer — 基于评估结果调优 harness 参数                 │ │
│  │   • Benchmark Runner — 批量运行任务集                         │ │
│  │   • Optimization Workspace — .lumos/optimization/             │ │
│  └───────────────────────────────────────────────────────────────┘ │
│                          ▲ consume trajectories, produce tuned     │
│                          │ harness config                          │
│  ┌───────────────────────────────────────────────────────────────┐ │
│  │ L6: TRAJECTORY LAYER  (行为记录)                               │ │
│  │   • TrajectoryLogger — 记录每个 turn / tool call / 决策点     │ │
│  │   • JSONL Storage — 结构化日志                                │ │
│  │   • Replay — 从日志重放任意行为序列                           │ │
│  └───────────────────────────────────────────────────────────────┘ │
│                          ▲ record all events                       │
│  ┌───────────────────────────────────────────────────────────────┐ │
│  │ L5: INTERCEPTOR LAYER  (统一拦截 — Harness 的核心横切机制)    │ │
│  │   • 10 个生命周期点，洋葱模型                                 │ │
│  │   • Python class 或 YAML shell 简写                           │ │
│  │   • 收编 hooks + middleware 为一套机制                         │ │
│  └───────────────────────────────────────────────────────────────┘ │
│                          ▲ intercept & transform                   │
│  ┌───────────────────────────────────────────────────────────────┐ │
│  │ L4: ORCHESTRATION LAYER  (编排层 — 现有 agent_loop 增强)      │ │
│  │   • agent_loop — 纯函数双层循环（保留）                       │ │
│  │   • Agent — 有状态壳（保留）                                  │ │
│  │   • ModeManager — BUILD/PLAN/REVIEW（保留）                   │ │
│  │   • Sub-agent Spawner — TaskTool（保留）                      │ │
│  └───────────────────────────────────────────────────────────────┘ │
│                          ▲ orchestrate                              │
│  ┌───────────────────────────────────────────────────────────────┐ │
│  │ L3: CAPABILITY LAYER  (能力层)                                 │ │
│  │   • ToolRegistry — AgentTool 注册/发现/schema（增强）         │ │
│  │   • SkillManager — SKILL.md 加载/匹配/注入（保留）            │ │
│  │   • PromptComposer — system prompt 动态组装（新增，详见§11）  │ │
│  │   • WorkspaceLoader — 加载 Workspace 上下文文件（新增）       │ │
│  └───────────────────────────────────────────────────────────────┘ │
│                          ▲ provide capabilities                    │
│  ┌───────────────────────────────────────────────────────────────┐ │
│  │ L2: STREAM LAYER  (流式通信层 — 现有，增强)                   │ │
│  │   • StreamFn Protocol — 可替换 LLM 调用（保留）               │ │
│  │   • EventStream — 异步事件流（保留）                          │ │
│  │   • MessageConverter — 内部格式 ↔ API 格式（保留）            │ │
│  │   • ModelRouter — 多模型路由（保留）                          │ │
│  └───────────────────────────────────────────────────────────────┘ │
│                          ▲ stream                                  │
│  ┌───────────────────────────────────────────────────────────────┐ │
│  │ L1: STATE LAYER  (状态层 — 现有，增强)                        │ │
│  │   • AgentState — messages / is_running / error（保留）        │ │
│  │   • Types — ContentBlock / AgentMessage / LLMConfig（保留）   │ │
│  │   • Abort / Steering / Follow-up Queues（保留）               │ │
│  └───────────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────────┘

   + Harness Package (可分发的 agent 行为配置包)
     安装后注入 L3 (tools, skills, prompts) + L5 (interceptors) + L4 (config)
```

### 3.1 每层的四个维度

每个模块同时具备：**可观测、可调优、可评估、可替换。**

| 模块 | 可观测 | 可调优 | 可评估 | 可替换 |
|---|---|---|---|---|
| agent_loop | 每轮 token 消耗、工具调用序列、耗时 | max_iterations, 循环终止条件 | 任务完成率、效率(steps/task) | 可替换不同循环策略 |
| PromptComposer | 每次组装的 prompt 内容和长度 | 模板、few-shot 示例 | 模型遵循指令的准确率 | DSPy-style 编译器 |
| ToolRegistry | 每个 tool call 的入参、出参、耗时、错误率 | 并行度、超时、重试策略 | 工具选择准确率 | 同接口不同实现 |
| SkillManager | skill 激活频率、匹配准确率 | 匹配阈值、优先级 | 激活 skill 后成功率变化 | 不同匹配策略 |
| ModeManager | 模式切换频率和时机 | 切换条件、工具白名单 | 模式选择与任务类型的匹配度 | 自动模式选择策略 |
| Interceptor Stack | 每个拦截器的执行耗时和效果 | 拦截器顺序、参数 | 拦截器对任务成功率的贡献 | 替换/增减拦截器 |

---

## 4. Interceptor 系统详细设计

### 4.1 设计动机

研究了 Claude Code Hooks（shell 确定性守卫）、Pi Agent Extensions（事件驱动能力注册）、DeepAgents Middleware（洋葱模型拦截）三种范式后，得出结论：

**它们本质上解决的是同一个问题 — "在 agent 生命周期的某个点上观察或改变行为"。** Lumos 应该只有一套机制，同时覆盖两种使用场景（Python 开发者 + 非开发者 YAML 配置）。

### 4.2 Interceptor Protocol

```python
"""lumos/interceptor/protocol.py"""

from __future__ import annotations
from typing import Any, Callable, Awaitable, Optional, Protocol, runtime_checkable


@runtime_checkable
class Interceptor(Protocol):
    """Lumos 唯一的生命周期拦截机制。
    
    洋葱模型：每个 interceptor 可以选择调用 proceed() 传递给下一层，
    也可以不调用（阻断），也可以修改输入/输出后再传递。
    """
    
    @property
    def name(self) -> str:
        """拦截器名称"""
        ...
    
    @property
    def priority(self) -> int:
        """执行优先级。数字越小越先执行（越外层）。默认 100。"""
        ...


class AgentInterceptor(Protocol):
    """Agent 级拦截点"""
    
    async def before_agent(
        self, ctx: AgentContext, proceed: ProceedFn
    ) -> AgentContext:
        """Agent 循环开始前。初始化状态、预处理。"""
        ...
    
    async def after_agent(
        self, ctx: AgentContext, proceed: ProceedFn
    ) -> AgentContext:
        """Agent 循环结束后。清理、持久化、统计。"""
        ...


class ModelInterceptor(Protocol):
    """Model 级拦截点"""
    
    async def before_model(
        self, request: ModelRequest, proceed: ProceedFn
    ) -> ModelRequest:
        """每次 LLM 调用前。注入上下文、过滤工具、修改 prompt。"""
        ...
    
    async def wrap_model(
        self, request: ModelRequest, handler: ModelHandler
    ) -> ModelResponse:
        """包裹 LLM 调用本身。重试、fallback、缓存、token 统计。"""
        ...
    
    async def after_model(
        self, response: ModelResponse, proceed: ProceedFn
    ) -> ModelResponse:
        """LLM 响应后。后处理、条件路由、质量检查。"""
        ...


class ToolInterceptor(Protocol):
    """Tool 级拦截点"""
    
    async def pre_tool_use(
        self, request: ToolRequest, proceed: ProceedFn
    ) -> ToolRequest:
        """工具执行前。approve/block/transform 输入。"""
        ...
    
    async def wrap_tool(
        self, request: ToolRequest, handler: ToolHandler
    ) -> ToolResult:
        """包裹工具执行。重试、缓存、审计、超时控制。"""
        ...
    
    async def post_tool_use(
        self, result: ToolResult, proceed: ProceedFn
    ) -> ToolResult:
        """工具执行后。transform 输出、触发副作用（lint、format）。"""
        ...


class ControlInterceptor(Protocol):
    """Control 级拦截点"""
    
    async def on_stop(
        self, ctx: StopContext, proceed: ProceedFn
    ) -> StopDecision:
        """Agent 要停止时。可以强制继续（如测试未通过）。"""
        ...
    
    async def on_error(
        self, error: AgentError, proceed: ProceedFn
    ) -> ErrorRecovery:
        """错误发生时。可恢复/重试/降级。"""
        ...


# 类型别名
ProceedFn = Callable[..., Awaitable[Any]]
ModelHandler = Callable[["ModelRequest"], Awaitable["ModelResponse"]]
ToolHandler = Callable[["ToolRequest"], Awaitable["ToolResult"]]
```

### 4.3 生命周期点一览

```
                    ┌─────────────────┐
                    │  before_agent   │  ← Agent 级
                    └────────┬────────┘
                             │
          ┌──────────────────▼──────────────────┐
          │            Turn Loop                 │
          │                                      │
          │  ┌──────────────────────────────┐   │
          │  │  before_model                │   │  ← Model 级
          │  │  wrap_model ──→ LLM API      │   │
          │  │  after_model                 │   │
          │  └──────────────┬───────────────┘   │
          │                 │                    │
          │  ┌──────────────▼───────────────┐   │
          │  │  for each tool_call:         │   │
          │  │    pre_tool_use              │   │  ← Tool 级
          │  │    wrap_tool ──→ Tool.execute │   │
          │  │    post_tool_use             │   │
          │  └──────────────┬───────────────┘   │
          │                 │                    │
          │       ┌─────────▼─────────┐         │
          │       │  stop? ──→ on_stop │        │  ← Control 级
          │       └───────────────────┘         │
          └─────────────────────────────────────┘
                             │
                    ┌────────▼────────┐
                    │  after_agent    │  ← Agent 级
                    └─────────────────┘
                             │
              (error at any point → on_error)
```

### 4.4 数据类型定义

```python
"""lumos/interceptor/types.py"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Optional

from lumos.core.types import AgentMessage, LLMConfig, AgentEvent
from lumos.core.tool import AgentTool


@dataclass
class AgentContext:
    """Agent 级上下文 — 贯穿整个 agent 生命周期"""
    messages: list[AgentMessage]
    tools: list[AgentTool]
    system_prompt: str
    llm_config: LLMConfig
    metadata: dict[str, Any] = field(default_factory=dict)  # 任意扩展数据
    session_id: Optional[str] = None
    cwd: Optional[str] = None


@dataclass
class ModelRequest:
    """Model 调用请求 — 每次 LLM 调用前构造"""
    messages: list[AgentMessage]
    system_prompt: str
    tools: list[AgentTool]
    model: str
    config: LLMConfig
    turn: int  # 当前是第几轮
    metadata: dict[str, Any] = field(default_factory=dict)
    
    def with_overrides(self, **kwargs) -> ModelRequest:
        """返回一个修改后的副本（不可变语义）"""
        from dataclasses import asdict
        data = asdict(self)
        data.update(kwargs)
        return ModelRequest(**data)


@dataclass
class ModelResponse:
    """Model 调用响应"""
    message: "AssistantMessage"
    usage: Optional[dict[str, int]] = None
    stop_reason: Optional[str] = None
    latency_ms: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass 
class ToolRequest:
    """Tool 调用请求"""
    tool_call_id: str
    tool_name: str
    arguments: dict[str, Any]
    tool: AgentTool
    turn: int
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ToolResult:
    """Tool 调用结果"""
    tool_call_id: str
    tool_name: str
    content: list  # list[ContentBlock]
    is_error: bool = False
    latency_ms: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class StopContext:
    """Stop 决策上下文"""
    reason: str  # "no_tool_calls" | "max_iterations" | "abort" | "follow_up_empty"
    messages: list[AgentMessage]
    turn: int
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class StopDecision:
    """Stop 决策结果"""
    should_stop: bool = True
    inject_messages: list[AgentMessage] = field(default_factory=list)
    reason: str = ""


@dataclass
class AgentError:
    """Agent 错误上下文"""
    exception: Exception
    phase: str  # "model" | "tool" | "loop"
    turn: int
    tool_name: Optional[str] = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ErrorRecovery:
    """错误恢复决策"""
    action: str  # "retry" | "skip" | "abort" | "fallback"
    retry_count: int = 0
    fallback_model: Optional[str] = None
    message: str = ""
```

### 4.5 洋葱模型执行引擎

```python
"""lumos/interceptor/engine.py"""

from __future__ import annotations
from typing import Any, Callable, Awaitable, Sequence
import logging

logger = logging.getLogger(__name__)


class InterceptorEngine:
    """拦截器执行引擎 — 洋葱模型
    
    对于每个生命周期点，按 priority 排序所有关心该事件的拦截器，
    然后从外到内依次调用，最内层是实际执行（agent_loop / stream_fn / tool.execute）。
    """
    
    def __init__(self):
        self._interceptors: list[Any] = []  # 所有注册的拦截器
        self._sorted = False
    
    def register(self, interceptor: Any) -> None:
        """注册拦截器"""
        self._interceptors.append(interceptor)
        self._sorted = False
    
    def unregister(self, name: str) -> bool:
        """按名称注销拦截器"""
        before = len(self._interceptors)
        self._interceptors = [
            i for i in self._interceptors
            if getattr(i, 'name', '') != name
        ]
        return len(self._interceptors) < before
    
    def _ensure_sorted(self) -> None:
        """按 priority 排序（lazy）"""
        if not self._sorted:
            self._interceptors.sort(
                key=lambda i: getattr(i, 'priority', 100)
            )
            self._sorted = True
    
    def _get_handlers(self, event_name: str) -> list:
        """获取关心指定事件的拦截器"""
        self._ensure_sorted()
        return [
            i for i in self._interceptors
            if hasattr(i, event_name) and callable(getattr(i, event_name))
        ]
    
    async def run_chain(
        self,
        event_name: str,
        initial_value: Any,
        core_fn: Callable[..., Awaitable[Any]],
        **kwargs,
    ) -> Any:
        """执行洋葱模型链
        
        Args:
            event_name: 生命周期点名称 (e.g. "before_model")
            initial_value: 传入的数据 (e.g. ModelRequest)
            core_fn: 最内层的实际执行函数
            **kwargs: 额外参数
            
        Returns:
            经过所有拦截器处理后的结果
        """
        handlers = self._get_handlers(event_name)
        
        if not handlers:
            return await core_fn(initial_value)
        
        # 构建洋葱链：handler_n → handler_n-1 → ... → handler_0 → core_fn
        async def build_chain(
            index: int, value: Any
        ) -> Any:
            if index >= len(handlers):
                return await core_fn(value)
            
            handler = handlers[index]
            method = getattr(handler, event_name)
            
            async def proceed(v: Any = None) -> Any:
                return await build_chain(index + 1, v if v is not None else value)
            
            try:
                return await method(value, proceed)
            except Exception as e:
                logger.error(
                    f"Interceptor '{getattr(handler, 'name', '?')}'"
                    f".{event_name} error: {e}"
                )
                raise
        
        return await build_chain(0, initial_value)
    
    async def run_wrap(
        self,
        event_name: str,
        request: Any,
        core_handler: Callable,
    ) -> Any:
        """执行 wrap 类型的洋葱链 (wrap_model, wrap_tool)
        
        与 run_chain 不同：wrap 类型的 handler 签名是 (request, handler) -> response，
        handler 是调用下一层的函数。
        """
        handlers = self._get_handlers(event_name)
        
        if not handlers:
            return await core_handler(request)
        
        # 从最内层开始包裹
        current_handler = core_handler
        for handler_obj in reversed(handlers):
            method = getattr(handler_obj, event_name)
            prev_handler = current_handler
            
            async def make_wrapper(m, h):
                async def wrapper(req):
                    return await m(req, h)
                return wrapper
            
            current_handler = await make_wrapper(method, prev_handler)
        
        return await current_handler(request)

### 4.6 Base 实现类（继承友好的默认实现）

```python
"""lumos/interceptor/base.py"""

from lumos.interceptor.protocol import ProceedFn
from lumos.interceptor.types import (
    AgentContext, ModelRequest, ModelResponse,
    ToolRequest, ToolResult, StopContext, StopDecision,
    AgentError, ErrorRecovery,
)


class BaseInterceptor:
    """Interceptor 的便利基类 — 所有方法都提供透传默认实现。
    
    子类只需覆盖关心的方法即可，不需要实现所有 10 个生命周期点。
    
    示例：
        class MyTracer(BaseInterceptor):
            name = "my-tracer"
            priority = 50
            
            async def before_model(self, request, proceed):
                print(f"[Trace] Calling model: {request.model}, turn={request.turn}")
                response = await proceed(request)
                print(f"[Trace] Model done, stop_reason={response.stop_reason}")
                return response
    """
    
    name: str = ""
    priority: int = 100  # 数字越小越外层

    async def before_agent(self, ctx: AgentContext, proceed: ProceedFn) -> AgentContext:
        return await proceed(ctx)

    async def after_agent(self, ctx: AgentContext, proceed: ProceedFn) -> AgentContext:
        return await proceed(ctx)

    async def before_model(self, request: ModelRequest, proceed: ProceedFn) -> ModelRequest:
        return await proceed(request)

    async def wrap_model(self, request: ModelRequest, handler) -> ModelResponse:
        return await handler(request)

    async def after_model(self, response: ModelResponse, proceed: ProceedFn) -> ModelResponse:
        return await proceed(response)

    async def pre_tool_use(self, request: ToolRequest, proceed: ProceedFn) -> ToolRequest:
        return await proceed(request)

    async def wrap_tool(self, request: ToolRequest, handler) -> ToolResult:
        return await handler(request)

    async def post_tool_use(self, result: ToolResult, proceed: ProceedFn) -> ToolResult:
        return await proceed(result)

    async def on_stop(self, ctx: StopContext, proceed: ProceedFn) -> StopDecision:
        return await proceed(ctx)

    async def on_error(self, error: AgentError, proceed: ProceedFn) -> ErrorRecovery:
        return await proceed(error)
```

### 4.7 YAML Shell 简写（非开发者接口）

开发者用 Python class，非开发者用 YAML 声明 shell 命令——两种方式统一为一套机制。

**harness/interceptors/safety.yaml:**

```yaml
name: safety-gate
priority: 10  # 最外层，最先执行

events:
  pre_tool_use:
    match: "bash|write_file|edit_file"   # 工具名正则，null = 全匹配
    command: "python3 hooks/safety_check.py"
    # stdin: JSON { tool_name, arguments }
    # exit 0 = approve, exit 1 = block (stderr 作为 reason), exit 2 = transform
    # stdout (exit 2): JSON { arguments: {...} }  修改后的参数
    timeout: 5

  post_tool_use:
    match: "write_file|edit_file"
    command: "npx prettier --write {file_path}"
    # {file_path} = arguments.file_path 的快捷模板变量
    timeout: 30

  stop:
    command: "python3 hooks/ensure_tests_pass.py"
    # 如果测试失败，输出 JSON { should_stop: false, inject: "Tests failed:\n..." }
    # 这会强制 agent 继续执行直到测试通过
    timeout: 60
```

**ShellInterceptor 自动生成（内部实现）：**

```python
"""lumos/interceptor/shell.py"""

import json
import asyncio
import subprocess
from lumos.interceptor.base import BaseInterceptor


class ShellInterceptor(BaseInterceptor):
    """从 YAML 配置自动生成的 shell 命令拦截器"""
    
    def __init__(self, config: dict):
        self.name = config["name"]
        self.priority = config.get("priority", 100)
        self._event_configs = config.get("events", {})
    
    async def pre_tool_use(self, request, proceed):
        cfg = self._event_configs.get("pre_tool_use")
        if not cfg:
            return await proceed(request)
        
        match = cfg.get("match")
        if match and not __import__("re").search(match, request.tool_name):
            return await proceed(request)
        
        stdin_data = json.dumps({
            "tool_name": request.tool_name,
            "arguments": request.arguments,
        })
        
        result = await self._run_command(
            cfg["command"], stdin_data, cfg.get("timeout", 10)
        )
        
        if result.returncode == 1:
            # Block: 用 stderr 作为错误原因注入 ToolResult
            from lumos.core.types import TextContent
            from lumos.interceptor.types import ToolResult
            return ToolResult(
                tool_call_id=request.tool_call_id,
                tool_name=request.tool_name,
                content=[TextContent(text=f"Blocked: {result.stderr}")],
                is_error=True,
            )
        elif result.returncode == 2:
            # Transform: 用 stdout 中的 JSON 更新参数
            try:
                new_args = json.loads(result.stdout)
                request = ToolRequest(
                    **{**request.__dict__, "arguments": new_args.get("arguments", request.arguments)}
                )
            except Exception:
                pass
        
        return await proceed(request)
    
    async def _run_command(self, command: str, stdin: str, timeout: int):
        return await asyncio.wait_for(
            asyncio.create_subprocess_shell(
                command,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            ),
            timeout=timeout,
        )
```

### 4.8 内置 Interceptor 示例

```python
"""lumos/interceptor/builtins/loop_detector.py"""

import re
from lumos.interceptor.base import BaseInterceptor


class WriteRmLoopDetector(BaseInterceptor):
    """检测 write_file → bash(rm) 循环反模式
    
    将现有 LumosAgent 中硬编码的 heuristic 迁移为可插拔的 interceptor。
    """
    
    name = "write-rm-loop-detector"
    priority = 80
    
    def __init__(self, threshold: int = 2):
        self._history: list[dict] = []
        self._threshold = threshold
        self._warned = False
    
    async def post_tool_use(self, result, proceed):
        self._history.append({
            "tool": result.tool_name,
            "content": result.content[0].text if result.content else "",
        })
        if len(self._history) > 50:
            self._history = self._history[-30:]
        
        if not self._warned:
            warning = self._detect()
            if warning:
                from lumos.core.types import TextContent
                # 将警告注入到工具结果末尾
                result.content.append(TextContent(text=warning))
                self._warned = True
        
        return await proceed(result)
    
    def _detect(self) -> str | None:
        write_files = set()
        rm_count = 0
        for entry in self._history[-10:]:
            if entry["tool"] == "write_file":
                write_files.add(entry["content"][:50])
            elif entry["tool"] == "bash":
                cmd = entry["content"]
                if "rm " in cmd:
                    for f in write_files:
                        if f[:20] in cmd:
                            rm_count += 1
        if rm_count >= self._threshold:
            return (
                "\n\n⚠️ [write-rm-loop-detector] 检测到 write_file → rm 循环！"
                "\n停止删除重试，改用 read_file 检查文件内容，用 edit_file 修复。"
            )
        return None
```

---

## 5. Trajectory Logger 设计

### 5.1 设计原则

- **完整性** — 记录每个 turn、每个 tool call、每个 LLM 响应、每个错误
- **结构化** — JSONL 格式，每行一个事件，方便流式写入和离线分析
- **低开销** — 异步写入，不阻塞 agent 主循环
- **可 replay** — 从日志可以重放任意行为序列，用于调试和评估

### 5.2 TrajectoryLogger（作为 Interceptor）

```python
"""lumos/trajectory/logger.py"""

from __future__ import annotations
import asyncio
import json
import time
import uuid
from pathlib import Path
from typing import Optional

from lumos.interceptor.base import BaseInterceptor
from lumos.interceptor.types import (
    AgentContext, ModelRequest, ModelResponse,
    ToolRequest, ToolResult, AgentError, ErrorRecovery,
)


class TrajectoryLogger(BaseInterceptor):
    """完整记录 agent 行为轨迹的 interceptor。
    
    作为 Interceptor 实现有两个优势：
    1. 无需修改 agent_loop 核心代码
    2. 可以随时通过 harness 安装/卸载
    
    数据格式: JSONL，每行一个事件。
    """
    
    name = "trajectory-logger"
    priority = 1  # 最高优先级，最外层，确保记录所有事件
    
    def __init__(
        self,
        output_dir: Path | str,
        session_id: Optional[str] = None,
        buffer_size: int = 100,
    ):
        self._dir = Path(output_dir)
        self._dir.mkdir(parents=True, exist_ok=True)
        self._session_id = session_id or str(uuid.uuid4())[:8]
        self._run_id = f"{int(time.time())}_{self._session_id}"
        self._file = self._dir / f"{self._run_id}.jsonl"
        self._buffer: list[dict] = []
        self._buffer_size = buffer_size
        self._lock = asyncio.Lock()
        self._start_time = time.time()
    
    # ── Agent 级 ──────────────────────────────────────────────────────
    
    async def before_agent(self, ctx: AgentContext, proceed):
        await self._emit("agent_start", {
            "session_id": self._session_id,
            "model": ctx.llm_config.model,
            "provider": ctx.llm_config.provider,
            "tools": [t.name for t in ctx.tools],
            "system_prompt_len": len(ctx.system_prompt),
        })
        result = await proceed(ctx)
        return result
    
    async def after_agent(self, ctx: AgentContext, proceed):
        result = await proceed(ctx)
        await self._emit("agent_end", {
            "session_id": self._session_id,
            "duration_s": time.time() - self._start_time,
            "message_count": len(ctx.messages),
        })
        await self._flush()  # 确保最后一批写入磁盘
        return result
    
    # ── Model 级 ──────────────────────────────────────────────────────
    
    async def before_model(self, request: ModelRequest, proceed):
        await self._emit("model_request", {
            "turn": request.turn,
            "model": request.model,
            "message_count": len(request.messages),
            "tools_count": len(request.tools),
            "system_prompt_len": len(request.system_prompt),
        })
        return await proceed(request)
    
    async def after_model(self, response: ModelResponse, proceed):
        await self._emit("model_response", {
            "stop_reason": response.stop_reason,
            "latency_ms": response.latency_ms,
            "usage": response.usage,
            "tool_calls": [
                {"name": tc.name, "id": tc.id}
                for tc in response.message.tool_calls
            ] if response.message.tool_calls else [],
            "text_len": len(response.message.text),
        })
        return await proceed(response)
    
    # ── Tool 级 ──────────────────────────────────────────────────────
    
    async def pre_tool_use(self, request: ToolRequest, proceed):
        await self._emit("tool_start", {
            "turn": request.turn,
            "tool_call_id": request.tool_call_id,
            "tool_name": request.tool_name,
            "arguments": request.arguments,
        })
        return await proceed(request)
    
    async def post_tool_use(self, result: ToolResult, proceed):
        await self._emit("tool_end", {
            "tool_call_id": result.tool_call_id,
            "tool_name": result.tool_name,
            "is_error": result.is_error,
            "latency_ms": result.latency_ms,
            "result_len": sum(
                len(getattr(c, "text", "")) for c in result.content
            ),
        })
        return await proceed(result)
    
    # ── Control 级 ──────────────────────────────────────────────────
    
    async def on_error(self, error: AgentError, proceed):
        await self._emit("error", {
            "phase": error.phase,
            "turn": error.turn,
            "tool_name": error.tool_name,
            "exception_type": type(error.exception).__name__,
            "message": str(error.exception),
        })
        return await proceed(error)
    
    # ── 内部写入 ──────────────────────────────────────────────────────
    
    async def _emit(self, event_type: str, data: dict) -> None:
        record = {
            "ts": time.time(),
            "run_id": self._run_id,
            "event": event_type,
            **data,
        }
        async with self._lock:
            self._buffer.append(record)
            if len(self._buffer) >= self._buffer_size:
                await self._flush_locked()
    
    async def _flush(self) -> None:
        async with self._lock:
            await self._flush_locked()
    
    async def _flush_locked(self) -> None:
        if not self._buffer:
            return
        lines = "\n".join(json.dumps(r, ensure_ascii=False) for r in self._buffer)
        await asyncio.to_thread(
            self._file.open("a", encoding="utf-8").write, lines + "\n"
        )
        self._buffer.clear()
```

### 5.3 JSONL 数据格式

每行是一个 JSON 对象，包含 `ts`（时间戳）、`run_id`、`event`（事件类型）和事件专属字段：

```jsonl
{"ts":1743580800.12,"run_id":"1743580800_a3f2","event":"agent_start","session_id":"a3f2","model":"claude-sonnet-4-6","provider":"anthropic","tools":["read_file","write_file","bash","grep"],"system_prompt_len":4832}
{"ts":1743580800.45,"run_id":"1743580800_a3f2","event":"model_request","turn":1,"model":"claude-sonnet-4-6","message_count":1,"tools_count":4,"system_prompt_len":4832}
{"ts":1743580802.31,"run_id":"1743580800_a3f2","event":"model_response","stop_reason":"tool_use","latency_ms":1860,"usage":{"input_tokens":1243,"output_tokens":87},"tool_calls":[{"name":"read_file","id":"call_abc123"}],"text_len":0}
{"ts":1743580802.33,"run_id":"1743580800_a3f2","event":"tool_start","turn":1,"tool_call_id":"call_abc123","tool_name":"read_file","arguments":{"file_path":"src/auth.py"}}
{"ts":1743580802.41,"run_id":"1743580800_a3f2","event":"tool_end","tool_call_id":"call_abc123","tool_name":"read_file","is_error":false,"latency_ms":80,"result_len":2341}
{"ts":1743580807.88,"run_id":"1743580800_a3f2","event":"agent_end","session_id":"a3f2","duration_s":7.76,"message_count":6}
```

### 5.4 目录结构与存储策略

```
.lumos/trajectories/
├── 1743580800_a3f2.jsonl    # 一个 run 一个文件
├── 1743580900_b7c1.jsonl
├── index.tsv                # 快速索引：run_id, start_ts, end_ts, turns, tool_calls, success
└── archive/                 # 7天后归档，压缩为 .jsonl.gz
```

**index.tsv** 格式（方便批量分析）：

```tsv
run_id          start_ts      end_ts        turns  tool_calls  duration_s  task_id          success
1743580800_a3f2 1743580800.12 1743580807.88 3      5           7.76        swe-bench-001   true
1743580900_b7c1 1743580900.00 1743580960.00 8      15          60.0        swe-bench-002   false
```

### 5.5 Trajectory Replay

```python
"""lumos/trajectory/replay.py"""

from __future__ import annotations
import json
from pathlib import Path
from typing import Iterator


class TrajectoryReplay:
    """从 JSONL 日志重放行为序列
    
    用途：
    - 调试：重放失败的 run，逐步检查每个决策点
    - 评估：批量加载 trajectory，计算 metrics
    - 可视化：生成时序图
    """
    
    def __init__(self, path: Path | str):
        self._path = Path(path)
    
    def events(self) -> Iterator[dict]:
        """迭代所有事件"""
        with self._path.open(encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    yield json.loads(line)
    
    def summary(self) -> dict:
        """计算 run 摘要统计"""
        turns = 0
        tool_calls = 0
        tool_errors = 0
        total_input_tokens = 0
        total_output_tokens = 0
        duration_s = 0.0
        
        for ev in self.events():
            if ev["event"] == "model_request":
                turns += 1
            elif ev["event"] == "tool_start":
                tool_calls += 1
            elif ev["event"] == "tool_end" and ev.get("is_error"):
                tool_errors += 1
            elif ev["event"] == "model_response":
                usage = ev.get("usage", {})
                total_input_tokens += usage.get("input_tokens", 0)
                total_output_tokens += usage.get("output_tokens", 0)
            elif ev["event"] == "agent_end":
                duration_s = ev.get("duration_s", 0)
        
        return {
            "turns": turns,
            "tool_calls": tool_calls,
            "tool_error_rate": tool_errors / max(tool_calls, 1),
            "input_tokens": total_input_tokens,
            "output_tokens": total_output_tokens,
            "duration_s": duration_s,
            "tools_per_turn": tool_calls / max(turns, 1),
        }
    
    def tool_sequence(self) -> list[str]:
        """提取工具调用序列（用于模式分析）"""
        return [
            ev["tool_name"]
            for ev in self.events()
            if ev["event"] == "tool_start"
        ]
```

---

## 6. Harness Package 设计

### 6.1 目录结构

一个 Harness Package 是一个包含以下目录的文件夹，每个目录**有且仅有一个清晰职责，互不重叠**：

```
my-harness/
├── HARNESS.yaml          # 清单：元数据 + 声明 + 组合方式
├── interceptors/         # 一切横切关注点的统一机制（Python class 或 YAML shell 简写）
├── tools/                # 给 LLM 用的能力（AgentTool 实现）
├── skills/               # 可激活的行为模式（SKILL.md，现有格式不变）
├── prompts/              # 静态 prompt 片段（始终生效，非 skill 激活）
└── config/               # 配置覆盖（模型参数、循环行为、子 agent 策略等）
```

**五个目录的职责边界：**

| 目录 | 本质 | 给谁用 | 不应该包含 |
|---|---|---|---|
| `interceptors/` | 代码，拦截 agent 生命周期 | Harness 运行时 | 业务逻辑工具 |
| `tools/` | 代码，暴露给 LLM 调用 | LLM（通过 tool_use） | 系统拦截逻辑 |
| `skills/` | Prompt，激活时注入 | LLM | 始终生效的 prompt |
| `prompts/` | Prompt，始终生效 | LLM | 可激活/可关闭的指令 |
| `config/` | 数据，覆盖默认配置 | Harness 运行时 | 任何代码 |

### 6.2 HARNESS.yaml 清单规范

```yaml
# HARNESS.yaml — 完整注释版

name: "swe-bench-optimized"
version: "1.2.0"
description: "Optimized harness for SWE-bench style coding task resolution"
author: "lumos-community/alice"
license: "MIT"

# ── 提供的资源 ────────────────────────────────────────────────
provides:
  
  # 拦截器列表（按优先级排序，数字越小越外层）
  interceptors:
    - path: interceptors/trajectory_logger.py
      class: TrajectoryLogger          # 指定类名（可选，默认按文件名推断）
      config:                          # 传递给 __init__ 的参数
        buffer_size: 50
    
    - path: interceptors/write_rm_detector.py
      class: WriteRmLoopDetector
    
    - path: interceptors/safety.yaml   # YAML shell 简写
    
    - path: interceptors/context_compressor.py
      class: SlidingWindowCondenser
      config:
        threshold_tokens: 80000
        strategy: "summarize_old"      # "truncate" | "summarize_old" | "keep_recent"
  
  # 工具（Python 文件，自动扫描 AgentTool 实例和工厂函数）
  tools:
    - interceptors/../tools/test_runner.py   # 相对路径
    - tools/repo_search.py
  
  # Skills（现有 SKILL.md 格式，完全向后兼容）
  skills:
    - skills/python-expert/SKILL.md
    - skills/git-workflow/SKILL.md
  
  # System Prompt 片段（始终附加，不需要激活）
  prompts:
    system_append: prompts/coding_guidelines.md   # 追加到 system prompt 末尾
    # system_prepend: prompts/context.md          # 前置（可选）
  
  # 配置覆盖
  config:
    path: config/overrides.yaml

# ── 组合方式 ────────────────────────────────────────────────
compose: layer       # "layer"（叠加在现有配置上）| "standalone"（独立使用）

# ── 兼容性声明 ────────────────────────────────────────────────
compatibility:
  lumos: ">=0.5.0,<1.0.0"
  python: ">=3.11"
  models:
    - "claude-sonnet-4-*"
    - "claude-opus-4-*"
    - "gpt-4o"
    - "gpt-4o-mini"

# ── 优化来源（透明度声明，不是可执行的配置）────────────────────
provenance:
  benchmark: "swe-bench-verified"
  score: 0.58
  baseline_score: 0.42
  optimization_rounds: 15
  trajectory_count: 500
  optimized_at: "2026-03-28"
  source_repo: "github.com/alice/lumos-swe-opt"  # 想复现优化过程的人去这里

# ── 依赖（安装时自动 pip install）────────────────────────────
dependencies:
  python:
    - "tree-sitter>=0.20"
    - "pygments>=2.0"
```

**config/overrides.yaml** 示例：

```yaml
# 配置覆盖 — 会与 Lumos 默认配置深度合并
behavior:
  max_iterations: 30        # 默认 100，SWE-bench 任务不需要那么多
  loop_detection: true

model:
  temperature: 0.2          # 编码任务用较低温度
  max_tokens: 8192

subagents:
  Explore:
    max_turns: 20           # 快速探索不需要太多轮
  Plan:
    max_turns: 15
  Bash:
    timeout_seconds: 120
```

### 6.3 HarnessLoader — 安装与加载

```python
"""lumos/harness/loader.py"""

from __future__ import annotations
import importlib.util
import sys
import inspect
from pathlib import Path
from typing import Any

import yaml

from lumos.interceptor.base import BaseInterceptor
from lumos.interceptor.shell import ShellInterceptor
from lumos.core.tool import AgentTool


class HarnessLoader:
    """从 harness 目录加载资源"""
    
    def __init__(self, harness_path: Path | str):
        self._root = Path(harness_path)
        self._manifest = self._load_manifest()
    
    def _load_manifest(self) -> dict:
        manifest_path = self._root / "HARNESS.yaml"
        if not manifest_path.exists():
            raise FileNotFoundError(f"HARNESS.yaml not found in {self._root}")
        with manifest_path.open(encoding="utf-8") as f:
            return yaml.safe_load(f)
    
    def load_interceptors(self) -> list[BaseInterceptor]:
        interceptors = []
        for spec in self._manifest.get("provides", {}).get("interceptors", []):
            path = self._root / spec["path"]
            
            if path.suffix == ".yaml":
                # YAML shell 简写 → 自动生成 ShellInterceptor
                with path.open() as f:
                    cfg = yaml.safe_load(f)
                interceptors.append(ShellInterceptor(cfg))
            else:
                # Python 文件 → 动态 import，找到指定类
                cls = self._import_class(path, spec.get("class"))
                config = spec.get("config", {})
                interceptors.append(cls(**config))
        
        return interceptors
    
    def load_tools(self) -> list[AgentTool]:
        tools = []
        for tool_path in self._manifest.get("provides", {}).get("tools", []):
            path = self._root / tool_path
            module = self._import_module(path)
            for name, obj in inspect.getmembers(module):
                if isinstance(obj, AgentTool):
                    tools.append(obj)
                elif callable(obj) and name.startswith("create_") and name.endswith("_tool"):
                    # 工厂函数约定
                    result = obj()
                    if isinstance(result, AgentTool):
                        tools.append(result)
        return tools
    
    def load_skills_dirs(self) -> list[Path]:
        skills = []
        for skill_path in self._manifest.get("provides", {}).get("skills", []):
            p = self._root / skill_path
            if p.exists():
                skills.append(p.parent)  # SkillManager 期望目录
        return skills
    
    def load_system_prompt_patch(self) -> str:
        prompts_cfg = self._manifest.get("provides", {}).get("prompts", {})
        patch = ""
        if append_path := prompts_cfg.get("system_append"):
            p = self._root / append_path
            if p.exists():
                patch += "\n\n" + p.read_text(encoding="utf-8")
        return patch
    
    def load_config(self) -> dict:
        config_spec = self._manifest.get("provides", {}).get("config", {})
        if isinstance(config_spec, dict):
            cfg_path = config_spec.get("path")
        else:
            cfg_path = config_spec
        if cfg_path:
            p = self._root / cfg_path
            if p.exists():
                with p.open() as f:
                    return yaml.safe_load(f) or {}
        return {}
    
    @property
    def metadata(self) -> dict:
        return {
            "name": self._manifest.get("name", ""),
            "version": self._manifest.get("version", ""),
            "description": self._manifest.get("description", ""),
            "provenance": self._manifest.get("provenance", {}),
        }
    
    def _import_module(self, path: Path):
        spec = importlib.util.spec_from_file_location(path.stem, path)
        module = importlib.util.module_from_spec(spec)
        sys.modules[path.stem] = module
        spec.loader.exec_module(module)
        return module
    
    def _import_class(self, path: Path, class_name: str | None):
        module = self._import_module(path)
        if class_name:
            return getattr(module, class_name)
        # 没指定类名：找第一个 BaseInterceptor 子类
        for name, obj in inspect.getmembers(module, inspect.isclass):
            if issubclass(obj, BaseInterceptor) and obj is not BaseInterceptor:
                return obj
        raise ValueError(f"No BaseInterceptor subclass found in {path}")
```

### 6.4 单活跃 Harness 模型

**核心原则：一个 agent 在一个时刻只有一种行为配置。** 类比 Python venv——你不会同时激活两个虚拟环境。

```
~/.lumos/packages/                   # 已安装的 harness（仓库）
├── swe-bench-optimized/
├── python-expert/
└── my-combined/

~/.lumos/config/lumos.yaml           # 全局配置
active_harness: swe-bench-optimized  # 当前激活的（只有一个）

<项目>/.lumos/config.yaml            # 项目级配置（覆盖全局）
active_harness: my-combined          # 项目可以用不同的 harness
```

运行时加载逻辑：
1. 检查项目级 `active_harness` → 找到就用
2. 否则检查全局 `active_harness` → 找到就用
3. 否则用 `default`（无 harness，纯内置行为）

**没有 stack、没有合并、没有冲突。加载一个目录就完事。**

### 6.5 Harness CLI

```bash
# 安装（只下载到 packages/，不激活）
lumos harness install ./my-harness
lumos harness install git:github.com/alice/my-harness

# 激活（同一时刻只有一个）
lumos harness use swe-bench-optimized

# 查看当前
lumos harness current
# → swe-bench-optimized (global)

# 切换
lumos harness use python-expert

# 回到默认（无 harness）
lumos harness use default

# 查看已安装
lumos harness list

# 查看详情
lumos harness info swe-bench-optimized
lumos harness inspect          # 当前激活的完整配置

# 验证 & 对比
lumos harness validate ./my-harness
lumos harness diff default swe-bench-optimized

# 卸载
lumos harness uninstall python-expert
```

### 6.6 Harness Compose（组合多个 harness）

如果需要两个 harness 的能力，**显式组合成一个新的**，而不是运行时隐式叠加：

```bash
lumos harness compose \
  --base swe-bench-optimized \
  --mixin python-expert \
  --name my-combined
```

组合逻辑：
- 以 `--base` 为基础，将 `--mixin` 的资源复制进来
- interceptors / tools / skills / prompts：追加
- config：`--mixin` 覆盖 `--base` 的同名字段
- 遇到同名 interceptor 或 tool 时：交互式询问保留哪个
- 产出一个独立的、完整的 harness 目录

```bash
lumos harness use my-combined    # 激活组合后的 harness
```

**组合是一次性的显式操作，产出一个新的独立 harness。运行时无需关心"它从哪来"。**

### 6.7 存储位置

```
~/.lumos/packages/                   # 用户全局
<项目>/.lumos/packages/              # 项目级（项目级 active_harness 优先从这里找）
```

---

## 7. Evaluation & Optimization 设计

### 7.1 分离原则

> **Evaluator 是锚点，不是货物。不打包进 Harness，独立于 agent。**

如果 evaluator 被打包进 harness，安装这个 harness 的人就同时获得了"选手"和"裁判"——这是自己批改自己的作业。Karpathy 的 `prepare.py` 是只读的不可变锚点，这个设计哲学必须保持。

```
harness package（分发给用户）          optimization workspace（开发者本地，不分发）
├── interceptors/                      ├── benchmarks/          ← 任务集（固定）
├── tools/                             ├── evaluators/          ← 评估函数（不可变）
├── skills/                            ├── trajectories/        ← 行为日志
├── prompts/                           ├── scores.tsv           ← 每轮优化分数
└── config/                            └── .git/                ← git 管理每轮变更
```

**生产 vs 优化的用户画像完全不同：**
- 普通用户：`lumos harness install swe-bench-optimized`，立刻获得优化后的 agent 行为
- 开发者/研究者：在本地 optimization workspace 里跑 benchmark、分析 trajectory、调整参数、再跑 benchmark

### 7.2 Evaluator 设计

```python
"""lumos/evaluator/base.py"""

from __future__ import annotations
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

from lumos.trajectory.replay import TrajectoryReplay


@dataclass
class EvalResult:
    score: float            # 0.0 ~ 1.0
    passed: bool
    details: dict[str, Any]
    reason: str = ""


class Evaluator(ABC):
    """不可变评估锚点。
    
    Evaluator 不能被 agent 修改，不能被打包进 harness，
    只能被 optimization loop 调用，产生 reward signal。
    
    实现约定（Karpathy's prepare.py style）：
    - 每个 Evaluator 是一个独立的 Python 文件
    - 包含一个 evaluate(trajectory, task) -> EvalResult 函数
    - 文件一旦建立，只追加不修改（immutable anchor）
    """
    
    @property
    @abstractmethod
    def name(self) -> str: ...
    
    @abstractmethod
    def evaluate(self, trajectory: TrajectoryReplay, task: dict) -> EvalResult:
        """评估一次 agent run 的质量。
        
        Args:
            trajectory: 从 JSONL 日志加载的行为轨迹
            task: 任务定义（benchmark 中的一个条目）
        
        Returns:
            EvalResult，包含 score 和详细信息
        """
        ...
```

**内置 Evaluator 示例（效率评估）：**

```python
"""lumos/evaluator/builtins/efficiency.py"""

from lumos.evaluator.base import Evaluator, EvalResult
from lumos.trajectory.replay import TrajectoryReplay


class EfficiencyEvaluator(Evaluator):
    """评估 agent 解决任务的效率（步数/token 使用）
    
    假设任务已完成，这个 evaluator 只评估"用了多少资源"。
    分数公式：1 / (1 + normalized_tool_calls + normalized_tokens)
    """
    
    name = "efficiency"
    
    def __init__(
        self,
        max_expected_tool_calls: int = 20,
        max_expected_tokens: int = 50000,
    ):
        self._max_tools = max_expected_tool_calls
        self._max_tokens = max_expected_tokens
    
    def evaluate(self, trajectory: TrajectoryReplay, task: dict) -> EvalResult:
        summary = trajectory.summary()
        
        tool_ratio = min(summary["tool_calls"] / self._max_tools, 2.0)
        token_ratio = min(
            (summary["input_tokens"] + summary["output_tokens"]) / self._max_tokens, 2.0
        )
        score = 1.0 / (1.0 + tool_ratio + token_ratio)
        
        return EvalResult(
            score=score,
            passed=score > 0.3,
            details={
                "tool_calls": summary["tool_calls"],
                "total_tokens": summary["input_tokens"] + summary["output_tokens"],
                "duration_s": summary["duration_s"],
                "tool_ratio": tool_ratio,
                "token_ratio": token_ratio,
            },
            reason=f"tool_calls={summary['tool_calls']}, tokens={summary['input_tokens'] + summary['output_tokens']}"
        )
```

### 7.3 Optimization Workspace 结构

```
.lumos/optimization/
├── WORKSPACE.yaml            # Workspace 配置：benchmark、目标 harness、评估指标
├── benchmarks/               # 任务集（固定，不变）
│   └── swe-bench-lite/
│       ├── tasks.jsonl       # 每行一个 task
│       └── README.md
├── evaluators/               # 评估函数（不可变锚点）
│   ├── task_completion.py    # 任务完成度
│   ├── efficiency.py         # 效率
│   └── code_quality.py       # 代码质量
├── trajectories/             # 行为日志（每轮 benchmark run 的输出）
│   └── round_015/
│       ├── task_001.jsonl
│       └── task_002.jsonl
├── scores.tsv                # 每轮优化分数记录
│   # round  score   delta   changed_what                             date
│   # 001    0.42    +0.00   baseline                                 2026-03-01
│   # 002    0.45    +0.03   add trajectory_logger interceptor        2026-03-02
│   # 015    0.58    +0.02   tune context compression threshold       2026-03-28
├── diffs/                    # 每轮变更的 git diff（可复现）
│   ├── round_002.patch
│   └── round_015.patch
└── .git/                     # git 管理，每轮优化是一个 commit
                              # keep-or-revert 机制：分数下降就 git revert
```

**WORKSPACE.yaml：**

```yaml
name: "lumos-swe-bench-opt"
target_harness: "../../harnesses/swe-bench-optimized"   # 被优化的 harness

benchmark:
  name: "swe-bench-lite"
  path: "benchmarks/swe-bench-lite/tasks.jsonl"
  sample_size: 50   # 每轮跑多少个 task（完整集太慢时用采样）

evaluators:
  primary: evaluators/task_completion.py    # 主指标（决定 keep/revert）
  secondary:
    - evaluators/efficiency.py
    - evaluators/code_quality.py

optimization:
  strategy: "hill_climb"    # "hill_climb" | "random_search" | "genetic"
  max_rounds: 50
  improvement_threshold: 0.01   # delta < 1% 则停止
  git_backed: true              # 每轮用 git commit，失败时 revert
```

### 7.4 Optimization Loop CLI

```bash
# 初始化 optimization workspace
lumos optimize init --benchmark swe-bench-lite --harness ./my-harness

# 运行一轮优化
lumos optimize run --rounds 1

# 批量运行
lumos optimize run --rounds 20

# 查看分数历史
lumos optimize scores

# 导出当前最优 harness
lumos optimize export --output ./optimized-harness

# 从已有 trajectory 重新评估（无需重跑 agent）
lumos optimize eval --trajectories .lumos/optimization/trajectories/round_015
```

---

## 8. 现有模块迁移方案

核心原则：**渐进迁移，不做大爆炸重写。** 每个改动向后兼容，保留所有现有接口。

### 8.1 agent_loop 改造

**现状：** `agent_loop` 是纯函数，直接调用 `stream_fn` 和 `tool.execute`，不经过任何拦截层。

**目标：** 在关键点插入 `InterceptorEngine` 调用，同时保留纯函数签名（通过可选参数注入）。

**改造方式：** 在 `agent_loop` 签名中新增可选的 `interceptor_engine` 参数，默认为 `None`（此时行为与当前完全一致）。

```python
# packages/server/core/agent_loop.py — 改造要点（不展示全部代码，只展示关键变更）

async def agent_loop(
    messages: list[AgentMessage],
    tools: list[AgentTool],
    llm_config: LLMConfig,
    loop_config: AgentLoopConfig,
    stream_fn: Optional[StreamFn] = None,
    abort_signal: Optional[Callable[[], bool]] = None,
    get_steering_messages: Optional[Callable[[], list[AgentMessage]]] = None,
    get_follow_up_messages: Optional[Callable[[], list[AgentMessage]]] = None,
    # ★ 新增可选参数，向后兼容
    interceptor_engine: Optional["InterceptorEngine"] = None,
) -> EventStream[AgentEvent]:
    """
    当 interceptor_engine 为 None 时，行为与现有版本完全一致。
    传入 engine 后，生命周期拦截自动生效。
    """
    ...

async def _run_loop(..., interceptor_engine):
    eng = interceptor_engine
    
    # before_agent
    ctx = AgentContext(messages=messages, tools=tools, ...)
    if eng:
        ctx = await eng.run_chain("before_agent", ctx, lambda c: c)
    
    # 内层循环中，before_model 替换原来的直接调用 stream_fn：
    async def _call_model(request: ModelRequest) -> ModelResponse:
        # wrap_model 调用 stream_fn
        return await stream_fn(request.messages, request.config, ...)
    
    request = ModelRequest(messages=messages, ...)
    if eng:
        # before_model
        request = await eng.run_chain("before_model", request, lambda r: r)
        # wrap_model
        response = await eng.run_wrap("wrap_model", request, _call_model)
        # after_model
        response = await eng.run_chain("after_model", response, lambda r: r)
    else:
        assistant_msg = await stream_fn(...)
        response = ModelResponse(message=assistant_msg, ...)
    
    # tool 执行中，pre/wrap/post_tool_use 替换原来的直接调用：
    async def _execute_tool(tool_req: ToolRequest) -> ToolResult:
        return await tool.execute(...)
    
    if eng:
        tool_req = ToolRequest(...)
        tool_req = await eng.run_chain("pre_tool_use", tool_req, lambda r: r)
        tool_result = await eng.run_wrap("wrap_tool", tool_req, _execute_tool)
        tool_result = await eng.run_chain("post_tool_use", tool_result, lambda r: r)
    else:
        result = await tool.execute(...)
```

**迁移影响：**
- ✅ 所有现有的 `agent_loop` 调用方（`Agent._run`、`LumosAgent` 等）无需修改
- ✅ `interceptor_engine=None` 时行为完全一致
- ✅ 新功能通过传入 engine 自动激活

### 8.2 Tool 系统改造

**现状：** `AgentTool` + `BaseTool` + `wrap_legacy_tool`，已是合理的双层抽象。

**改造方向：** 仅在 `AgentTool` 上增加 `tags` 和 `category` 元数据，用于 harness 中的工具过滤。

```python
# packages/server/core/tool.py — 仅新增字段，不改动任何现有逻辑

class AgentTool:
    def __init__(
        self,
        name: str,
        description: str,
        parameters: dict[str, Any],
        execute_fn: ExecuteFn,
        label: str = "",
        # ★ 新增可选元数据
        tags: list[str] | None = None,      # e.g. ["filesystem", "write"]
        category: str = "",                  # e.g. "filesystem" | "web" | "shell"
    ):
        ...
        self.tags = tags or []
        self.category = category
```

`BaseTool` 和 `wrap_legacy_tool` **不需要任何改动**，完全向后兼容。

### 8.3 Skill 系统改造

**现状：** `SkillManager` 负责加载、匹配、激活、过滤工具。现有 SKILL.md 格式保持不变。

**改造方向：** `SkillManager` 增加从 harness 安装的 skills 目录作为加载源，优先级在用户全局 skills 之后、项目级 skills 之前。

```python
# packages/server/skills/loader.py — 新增 harness skills 目录

class SkillLoader:
    def __init__(self, project_root=None, harness_skill_dirs=None):
        ...
        # ★ 新增：从 harness 安装的 skills 目录
        self._harness_dirs: list[Path] = harness_skill_dirs or []
    
    def _get_search_dirs(self) -> list[Path]:
        """优先级从高到低：项目级 > harness > 用户全局"""
        dirs = []
        if self._project_root:
            dirs.append(self._project_root / ".lumos" / "skills")
        dirs.extend(self._harness_dirs)         # ★ 新增
        dirs.append(Path.home() / ".lumos" / "skills")
        return [d for d in dirs if d.exists()]
```

**迁移影响：**
- ✅ 现有 SKILL.md 格式完全不变
- ✅ 现有 `SkillManager` 使用方式不变
- ✅ Harness 的 skills 自动被发现，无需手动注册

### 8.4 Mode 系统改造

**现状：** `AgentModeManager` + `AgentMode` 枚举，三种模式，固定权限配置。

**改造方向：** 允许 harness 的 `config/overrides.yaml` 覆盖模式权限（工具白名单、阻止命令），但不改变模式的本质语义（BUILD/PLAN/REVIEW 保留）。

```python
# packages/server/agents/mode_manager.py — 支持外部配置覆盖

class AgentModeManager:
    def __init__(
        self,
        initial_mode: AgentMode = AgentMode.BUILD,
        config_overrides: dict | None = None,   # ★ 新增：来自 harness config
    ):
        self.current_mode = initial_mode
        self._overrides = config_overrides or {}
        self.mode_configs = self._init_mode_configs()
    
    def _init_mode_configs(self) -> dict:
        base_configs = { ... }  # 现有逻辑不变
        
        # ★ 应用 harness 配置覆盖
        mode_overrides = self._overrides.get("modes", {})
        for mode_name, override in mode_overrides.items():
            mode = AgentMode(mode_name)
            if mode in base_configs:
                cfg = base_configs[mode]
                if "extra_tools" in override:
                    cfg.allowed_tools |= set(override["extra_tools"])
                if "blocked_commands" in override:
                    cfg.blocked_commands |= set(override["blocked_commands"])
        
        return base_configs
```

**迁移影响：**
- ✅ 现有 BUILD/PLAN/REVIEW 三模式完全保留
- ✅ 默认行为（`config_overrides=None`）与现在完全一致
- ✅ Harness 可以细粒度扩展权限（如为特定项目在 PLAN 模式中允许 `git log`）

---

## 9. 新增模块清单与依赖图

### 9.1 新增模块清单

| 模块 | 路径 | 职责 | 依赖 |
|---|---|---|---|
| `InterceptorEngine` | `lumos/interceptor/engine.py` | 洋葱模型执行引擎 | 无外部依赖 |
| `BaseInterceptor` | `lumos/interceptor/base.py` | 便利基类，默认透传 | `protocol.py`, `types.py` |
| `InterceptorTypes` | `lumos/interceptor/types.py` | 数据类型（Request/Response/Context） | `core.types` |
| `ShellInterceptor` | `lumos/interceptor/shell.py` | YAML shell 简写自动生成 | `base.py`, `asyncio` |
| `WriteRmLoopDetector` | `lumos/interceptor/builtins/loop_detector.py` | 循环检测（迁移自 LumosAgent） | `base.py` |
| `ContextCompressor` | `lumos/interceptor/builtins/context_compressor.py` | 上下文窗口管理 | `base.py`, `core.types` |
| `TrajectoryLogger` | `lumos/trajectory/logger.py` | 行为记录（作为 Interceptor） | `base.py`, `asyncio` |
| `TrajectoryReplay` | `lumos/trajectory/replay.py` | 从 JSONL 重放行为 | `json`, `pathlib` |
| `Evaluator` | `lumos/evaluator/base.py` | 不可变评估锚点基类 | `replay.py` |
| `EfficiencyEvaluator` | `lumos/evaluator/builtins/efficiency.py` | 效率评估 | `base.py` |
| `HarnessLoader` | `lumos/harness/loader.py` | 从 harness 目录加载资源 | `yaml`, `importlib` |
| `HarnessManager` | `lumos/harness/manager.py` | 安装/卸载/激活 harness | `loader.py` |
| `HarnessCLI` | `lumos/cli/harness.py` | `lumos harness *` 命令 | `manager.py`, `click` |
| `OptimizeCLI` | `lumos/cli/optimize.py` | `lumos optimize *` 命令 | `evaluator`, `trajectory`, `harness` |
| `PromptComposer` | `lumos/capability/prompt_composer.py` | system prompt 动态组装 | `skill_manager`, `mode_manager` |

### 9.2 依赖图

```
┌──────────────────────────────────────────────────────────────────────┐
│                           新增模块依赖关系                            │
│                                                                       │
│  CLI Layer                                                            │
│  ┌──────────────┐    ┌──────────────┐                               │
│  │  HarnessCLI  │    │  OptimizeCLI │                               │
│  └──────┬───────┘    └──────┬───────┘                               │
│         │                   │                                         │
│  Harness Layer              │ Optimization Layer                      │
│  ┌──────▼────────────┐     ┌▼──────────────────────────────────┐    │
│  │  HarnessManager   │     │  OptimizationWorkspace             │    │
│  │  HarnessLoader    │     │  BenchmarkRunner                   │    │
│  └──────┬────────────┘     │  Evaluator (base + builtins)       │    │
│         │                   └──────────────────┬────────────────┘    │
│         │                                       │                     │
│  ┌──────▼───────────────────────────────────┐  │                    │
│  │  Interceptor Layer                        │  │                    │
│  │  InterceptorEngine                        │  │                    │
│  │  BaseInterceptor                          │  │                    │
│  │  ShellInterceptor                         │  │                    │
│  │  Builtins (WriteRmLoopDetector, etc.)     │  │                    │
│  │  TrajectoryLogger ◄──────────────────────────┘                   │
│  └──────┬────────────────────────────────────┘                      │
│         │                                                             │
│  ┌──────▼──────────────────────────────────────┐                    │
│  │  Core Layer (现有，小改动)                    │                    │
│  │  agent_loop (+ interceptor_engine 参数)      │                    │
│  │  AgentTool (+ tags, category 字段)           │                    │
│  │  SkillManager (+ harness_skill_dirs 参数)    │                    │
│  │  AgentModeManager (+ config_overrides 参数)  │                    │
│  └──────┬──────────────────────────────────────┘                    │
│         │                                                             │
│  ┌──────▼──────────────────────┐                                    │
│  │  Trajectory Layer           │                                     │
│  │  TrajectoryReplay           │                                     │
│  │  TrajectoryIndex            │                                     │
│  └─────────────────────────────┘                                    │
└──────────────────────────────────────────────────────────────────────┘
```

---

## 10. 分阶段实施路线图

### Phase 1 — 观测基础（2 周）

**目标：** 让 agent 的行为变得可观测，完成"数据飞轮"的数据采集端。

**交付物：**

1. `InterceptorEngine` + `BaseInterceptor` + 所有数据类型（`InterceptorTypes`）
2. `agent_loop` 增加 `interceptor_engine` 可选参数（向后兼容）
3. `TrajectoryLogger`（作为 Interceptor，挂在 `before/after_agent`、`before/after_model`、`pre/post_tool_use`、`on_error` 上）
4. `TrajectoryReplay` + `TrajectoryReplay.summary()` + `TrajectoryReplay.tool_sequence()`
5. `ShellInterceptor`（YAML shell 简写加载器）
6. 将 `LumosAgent` 中硬编码的 `_detect_write_rm_loop` 迁移为 `WriteRmLoopDetector` interceptor

**验收标准：**
- 每次 agent run 自动生成 JSONL 日志（默认路径 `~/.lumos/trajectories/`）
- `TrajectoryReplay.summary()` 能正确统计 turns / tool_calls / tokens / duration
- 向后兼容：不传 `interceptor_engine` 时行为与现在完全一致
- 单测覆盖 `InterceptorEngine` 洋葱模型的透传、阻断、变换三种场景

**不做：** Harness Package、评估器、优化循环（Phase 2/3 的事）

---

### Phase 2 — Harness Package（2 周）

**目标：** 让 harness 配置可以被打包、安装、分发。

**交付物：**

1. `HarnessLoader` — 从 `HARNESS.yaml` 加载 interceptors / tools / skills / prompts / config
2. `HarnessManager` — 安装（本地路径、git URL）、卸载、激活、列出
3. `HarnessCLI` — `lumos harness install/list/use/remove/inspect/validate`
4. `LumosAgent` 改造：初始化时加载激活的 harness，将 interceptors 注入 engine，将 harness tools/skills 加入对应 registry
5. `ContextCompressor` 内置 interceptor（`before_model`，sliding window / summarize_old 策略）
6. `AgentModeManager` 支持 harness config overrides
7. `SkillManager` 支持 harness skill dirs

**验收标准：**
- `lumos harness install ./test-harness` 能正确加载 interceptors 并在下次 agent run 中生效
- `lumos harness inspect` 输出每层的拦截器列表和来源
- YAML shell 简写的 `pre_tool_use` 能正确 approve / block / transform 工具调用
- 一个 E2E 测试：安装带 TrajectoryLogger 的 harness，跑一次 agent，验证 JSONL 输出存在且结构正确

**不做：** 评估器、优化循环（Phase 3 的事）

---

### Phase 3 — Evaluation & Optimization（3 周）

**目标：** 完成自优化闭环的评估端，能够量化衡量 harness 配置的效果。

**交付物：**

1. `Evaluator` 基类 + 内置 evaluators（效率、工具选择准确率、循环检测触发率）
2. `BenchmarkRunner` — 批量运行 benchmark 任务集，并行收集 trajectory
3. `Optimization Workspace` 初始化（`lumos optimize init`）
4. `scores.tsv` 写入逻辑 + `git commit` 每轮变更
5. `lumos optimize run --rounds N` — 基础的 hill-climbing 优化
6. `lumos optimize export` — 将当前最优配置导出为 Harness Package
7. 对接 SWE-bench-lite 作为第一个 benchmark（提供 `tasks.jsonl` 和对应的 `task_completion.py` evaluator）

**验收标准：**
- 能跑通一个完整的优化循环：init → run 5 rounds → export → install 导出的 harness
- `scores.tsv` 正确记录每轮分数和变更说明
- 每轮 git commit 可以 revert（验证 keep-or-revert 机制）
- 分离验证：Evaluator 和 agent 在不同进程中运行，agent 无法修改 evaluator

---

### Phase 4 — 生态成熟（持续）

**目标：** 将 Lumos 打磨为一个对开发者友好的、社区可共建的 harness 框架。

**交付物（优先级从高到低）：**

1. **Harness Registry**（基于 git，类似 npm registry）
   - `lumos harness publish` — 推送到社区 registry
   - 支持按 benchmark 分数排序浏览
   - provenance 验证（分数来源可追溯）

2. **更多内置 interceptors**
   - `RepoMapInjector` — tree-sitter 解析项目结构，自动注入 system prompt
   - `AutoLintInterceptor` — 编辑后自动运行 linter
   - `CostBudgetInterceptor` — token/cost 预算控制

3. **更多 Evaluators**
   - `TaskCompletionEvaluator` — 任务完成度（对接 SWE-bench / τ-bench）
   - `CodeQualityEvaluator` — 代码质量（lint 通过率、test 通过率）

4. **更多 Benchmarks 对接**
   - τ-bench（Agent + Tool + User 交互）
   - GAIA（通用助手）
   - Aider Polyglot（多语言代码编辑）

---

## 11. Workspace & System Prompt 系统

### 11.1 问题

当前 Lumos 的 system prompt 是 `LumosAgent.DEFAULT_SYSTEM_PROMPT` 里一个 ~300 行的硬编码字符串，包含身份定义、工具使用规则、任务管理规则、代码风格规范等全部揉在一起。

**问题**:
1. 不可定制——用户无法改变 Agent 的身份、规范、偏好
2. 不可分层——项目级规范和全局规范混在一起
3. 不可扩展——Harness Package 的 `prompts/` 没有注入机制
4. 与 Skill 的关系不清晰——Skill prompt 和 system prompt 怎么组合？
5. 缺少 workspace 上下文——Agent 不知道"在哪个项目""项目结构是什么""团队规范是什么"

### 11.2 对标

| 系统 | Workspace 文件 | 注入方式 |
|---|---|---|
| **OpenClaw** | AGENTS.md, SOUL.md, USER.md, IDENTITY.md, TOOLS.md, MEMORY.md | 框架自动加载，拼接到 system prompt 的 "Project Context" section |
| **yoyo-evolve** | IDENTITY.md, PERSONALITY.md, ECONOMICS.md, active_learnings.md | `yoyo_context.sh` 用 section 标记拼接（WHO YOU ARE / YOUR VOICE / SELF-WISDOM...） |
| **Claude Code** | CLAUDE.md（项目级 + 全局级 + 子目录级） | 自动搜索并加载，支持层级覆盖 |

共性：分层加载（全局→项目级）、约定文件名自动加载、Markdown 用户可编辑。

### 11.3 Workspace 目录结构

```
~/.lumos/                           # 全局 workspace (用户 home)
├── AGENT.md                        # 全局 Agent 行为规范
├── IDENTITY.md                     # Agent 身份（名字、人格、语气）
├── USER.md                         # 用户信息（偏好、时区、习惯）
├── TOOLS.md                        # 本地工具备忘录
├── memory/                         # 全局记忆
│   ├── MEMORY.md                   # 长期记忆（curated）
│   ├── learnings.jsonl             # 反思归档（只追加）
│   ├── active_insights.md          # 活跃洞察（synthesis 生成）
│   └── YYYY-MM-DD.md              # 每日笔记
├── packages/                       # 已安装的 Harness Packages
└── config/                         # 全局配置
    └── lumos.yaml

<项目根目录>/                        # 项目 workspace
├── LUMOS.md                        # 项目级指令（对标 CLAUDE.md）
├── .lumos/
│   ├── config.yaml                 # 项目级配置
│   ├── memory/                     # 项目级记忆
│   │   ├── learnings.jsonl
│   │   └── active_insights.md
│   └── packages/                   # 项目级 Harness Packages
└── <子目录>/
    └── LUMOS.md                    # 子目录级指令（可选）
```

### 11.4 各文件职责

| 文件 | 层级 | 职责 | 对标 |
|---|---|---|---|
| `AGENT.md` | 全局 | Agent 行为规范：什么可以做、什么不可以、怎么做 | OpenClaw AGENTS.md |
| `IDENTITY.md` | 全局 | Agent 身份：名字、人格、语气、emoji | OpenClaw SOUL.md + yoyo IDENTITY.md |
| `USER.md` | 全局 | 用户信息：名字、时区、偏好、备注 | OpenClaw USER.md |
| `TOOLS.md` | 全局 | 本地工具/环境备忘录 | OpenClaw TOOLS.md |
| `LUMOS.md` | 项目级 | 项目指令：架构、规范、构建命令、注意事项 | Claude Code CLAUDE.md / yoyo YOYO.md |
| `MEMORY.md` | 全局 | 长期记忆（人工 curated） | OpenClaw MEMORY.md |
| `learnings.jsonl` | 两级 | 反思归档（Agent 自动追加） | yoyo learnings.jsonl |
| `active_insights.md` | 两级 | 活跃洞察（synthesis 定期生成） | yoyo active_learnings.md |

**兼容性**：同时搜索 `LUMOS.md` 和 `CLAUDE.md`，LUMOS.md 优先。从 Claude Code 迁移的用户可以直接用现有 CLAUDE.md。

### 11.5 PromptComposer — System Prompt 动态组装

```python
class PromptComposer:
    """System prompt 的动态组装器

    职责：
    1. 加载 workspace 文件（AGENT.md, IDENTITY.md, USER.md, LUMOS.md）
    2. 加载 Harness Package 的 prompts/
    3. 加载活跃 Skill 的 prompt
    4. 加载活跃记忆（active_insights.md）
    5. 注入运行时上下文（工作目录、git 状态）
    6. 按优先级分层组装，控制总 token 量
    """

    def __init__(
        self,
        global_workspace: Path,        # ~/.lumos/
        project_root: Optional[Path],  # 项目根目录
        harness_packages: list["HarnessPackage"],
        skill_manager: "SkillManager",
        mode_manager: "ModeManager",
    ): ...

    def compose(self, runtime_context: dict) -> str:
        """组装完整的 system prompt"""
        sections: list[PromptSection] = []
        sections.append(self._load_core_identity())       # L1
        sections.append(self._load_agent_rules())          # L2
        sections.append(self._load_user_context())         # L3
        sections.append(self._load_project_instructions()) # L4
        for pkg in self.harness_packages:
            sections.append(self._load_package_prompts(pkg))  # L5
        sections.append(self._load_skill_prompt())         # L6
        sections.append(self._load_mode_prompt())          # L7
        sections.append(self._load_active_insights())      # L8
        sections.append(self._load_runtime_context(runtime_context))  # L9
        return self._assemble(sections)
```

### 11.6 分层组装与压缩优先级

```
┌───────────────────────────────────────────────────┐
│ System Prompt 9 层组装（由上到下优先级递减）        │
│                                                    │
│ L1: 核心身份 (IDENTITY.md)              [不可压缩] │
│ L2: 行为规范 (AGENT.md + 内置规则)      [不可压缩] │
│ L3: 用户信息 (USER.md)                 [可轻压缩] │
│ L4: 项目指令 (LUMOS.md)                [可轻压缩] │
│ L5: Harness Package prompts            [可压缩]   │
│ L6: 活跃 Skill prompt                  [可压缩]   │
│ L7: 模式提示 (BUILD/PLAN/REVIEW)       [可压缩]   │
│ L8: 活跃记忆 (active_insights.md)      [可压缩]   │
│ L9: 运行时上下文                        [动态]    │
│                                                    │
│ 当总 token 超预算时，从 L8→L5 依次压缩/裁剪       │
│ L1-L3 永远不压缩                                   │
└───────────────────────────────────────────────────┘
```

### 11.7 PromptSection 数据结构

```python
@dataclass
class PromptSection:
    name: str                      # section 名称
    content: str                   # 内容
    priority: int                  # 1-9, 1 最高
    compressible: bool = True      # 是否可以被压缩
    source: str = ""               # 来源文件路径（调试用）
    token_estimate: int = 0        # 预估 token 数

    def to_prompt(self) -> str:
        return f"=== {self.name.upper()} ===\n\n{self.content}\n"
```

### 11.8 文件加载规则

- **LUMOS.md 级联**: 从当前目录向上搜索到项目根，所有找到的 LUMOS.md 合并（项目根在前，子目录在后）
- **身份文件**: 项目级 `.lumos/IDENTITY.md` 覆盖全局 `~/.lumos/IDENTITY.md`，未找到则使用内置默认值
- **兼容性**: 搜索 `LUMOS.md` 和 `CLAUDE.md`，LUMOS.md 优先

### 11.9 首次运行引导

```bash
# 项目初始化（生成 LUMOS.md）
lumos init
# - 扫描项目结构（语言、框架、构建系统）
# - 检测现有 CLAUDE.md / YOYO.md（提示是否迁移）
# - 自动生成 LUMOS.md

# 全局初始化（首次使用 Lumos）
lumos setup
# - 交互式引导：Agent 名字、用户名字、时区、偏好语言
# - 生成 ~/.lumos/IDENTITY.md, USER.md, AGENT.md
```

### 11.10 与 Harness Package L3 层的映射

PromptComposer 位于 L3 Capability Layer，负责组装传给 LLM 的完整 system prompt：

- Harness Package 的 `prompts/` → L5 注入
- Harness Package 的 `skills/` → L6 通过 SkillManager 激活
- Harness Package 的 `config/` → 影响 L7 模式提示
- Interceptor 的 `before_model` → 可以在 L5 之上动态注入内容（如 RepoMapInjector）

---

## 12. 记忆系统设计

### 12.1 设计来源

采纳 yoyo-evolve 的三层时间衰减记忆系统（详见 [yoyo-evolve 调研报告](./research-yoyo-evolve.md)），结合 Lumos 的 Trajectory Logger 形成双轨记忆。

### 12.2 双轨记忆架构

```
┌──────────────────────────────────────────────────┐
│ 轨道 1: 结构化 Trajectory（程序可分析）            │
│                                                   │
│ 来源: TrajectoryLogger (Interceptor 自动记录)     │
│ 格式: JSONL                                       │
│ 内容: 每个 turn/tool call 的精确数据              │
│ 用途: Evaluator 量化分析 + Optimizer 调参         │
│ 保留: ~7 天后归档压缩                             │
└──────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────┐
│ 轨道 2: 自然语言 Learnings（人类可阅读）          │
│                                                   │
│ 来源: Agent 自我反思（session 结束时追加）         │
│ 格式: JSONL (只追加不删除)                        │
│ 内容: lesson + context (元认知、模式识别)         │
│ 用途: 注入 system prompt，影响 Agent 未来行为     │
│ 保留: 永久                                        │
└──────────────────────────────────────────────────┘

      │ Synthesis (定期)
      ▼

┌──────────────────────────────────────────────────┐
│ 活跃层: active_insights.md                        │
│                                                   │
│ ## Recent (最近 2 周)                             │
│ 完整的 lesson + context                           │
│                                                   │
│ ## Medium (2-8 周)                                │
│ 按主题聚合的 lesson 精华                          │
│                                                   │
│ ## Foundational                                   │
│ 核心原则（不带日期，永久保留）                    │
└──────────────────────────────────────────────────┘
```

### 12.3 learnings.jsonl 格式

```jsonl
{"ts":"2026-04-04T23:00:00Z","session_id":"abc123","type":"reflection","lesson":"上下文压缩在长任务中导致关键信息丢失","context":"在跑第15轮SWE-bench时，agent忘记了前10轮修改的文件...","source":"self-dev-pipeline"}
{"ts":"2026-04-04T23:30:00Z","session_id":"abc123","type":"trajectory_summary","tasks_planned":3,"tasks_completed":1,"tokens_used":45000,"tools":["read_file","edit_file","bash"],"duration_s":1200}
```

### 12.4 MemorySynthesizer

```python
class MemorySynthesizer:
    """从 learnings.jsonl 生成 active_insights.md

    触发时机：
    - 每日一次（cron / heartbeat）
    - session 结束时（如果距上次 synthesis > 24h）
    
    三层时间衰减（采纳 yoyo-evolve 设计）：
    - Recent (< 2 周): 保留完整 Context + Lesson
    - Medium (2-8 周): 只保留 Lesson 精华，按主题归类
    - Foundational (> 8 周): 不带日期的核心原则
    """

    def synthesize(self, jsonl_path: Path, output_path: Path):
        entries = self._load_entries(jsonl_path)
        now = datetime.utcnow()

        recent = [e for e in entries if (now - e.ts).days <= 14]
        medium = [e for e in entries if 14 < (now - e.ts).days <= 56]
        old = [e for e in entries if (now - e.ts).days > 56]

        sections = []
        sections.append("# Active Insights\n")

        sections.append("## Recent (Last 2 Weeks)\n")
        for e in recent:
            sections.append(self._format_full(e))

        sections.append("## Medium (2-8 Weeks)\n")
        themes = self._cluster_by_theme(medium)
        for theme, entries in themes.items():
            sections.append(self._format_theme(theme, entries))

        sections.append("## Foundational\n")
        principles = self._extract_principles(old)
        for p in principles:
            sections.append(f"- {p}\n")

        output_path.write_text("\n".join(sections))
```

### 12.5 记忆注入 System Prompt

通过 PromptComposer 的 L8 层注入：

```python
def _load_active_insights(self) -> PromptSection:
    """加载活跃洞察，注入 system prompt"""
    paths = [
        self.project_root / ".lumos" / "memory" / "active_insights.md",
        self.global_workspace / "memory" / "active_insights.md",
    ]
    content = ""
    for p in paths:
        if p.exists():
            content += p.read_text(encoding="utf-8") + "\n"
    
    return PromptSection(
        name="Self-Wisdom",
        content=content or "No insights yet.",
        priority=8,
        compressible=True,
        source=str(paths[0]),
    )
```

### 12.6 与 Phase 1-4 路线图的关系

| 记忆组件 | 所属 Phase | 依赖 |
|---|---|---|
| TrajectoryLogger (JSONL) | Phase 1 | InterceptorEngine |
| learnings.jsonl 追加 | Phase 2 | TrajectoryLogger (可选) |
| MemorySynthesizer | Phase 2 | learnings.jsonl |
| active_insights.md → PromptComposer | Phase 2 | MemorySynthesizer + PromptComposer |
| Evaluator 消费 Trajectory | Phase 3 | TrajectoryReplay |