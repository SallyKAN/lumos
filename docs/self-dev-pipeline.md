# Lumos Self-Development Pipeline 设计文档

> **让 Lumos 用自己的 Harness 机制来开发自己，对标 Claude Code 的能力。**
>
> 版本：v1.0-draft
> 日期：2026-04-04
> 作者：Lumos Architecture Team

---

## 目录

1. [概述](#1-概述)
2. [两阶段关系图](#2-两阶段关系图)
3. [self-dev-harness 目录结构](#3-self-dev-harness-目录结构)
4. [Pipeline 状态机](#4-pipeline-状态机)
5. [Gap Analyzer 设计](#5-gap-analyzer-设计)
6. [调度器设计](#6-调度器设计)
7. [IM 集成](#7-im-集成)
8. [阶段一的最小依赖](#8-阶段一的最小依赖)
9. [分阶段实施路线图](#9-分阶段实施路线图)
10. [Dogfooding 验证](#10-dogfooding-验证)

---

## 1. 概述

### 1.1 这个方案是什么

Self-Development Pipeline 是一个让 Lumos **使用自身的 Harness Package 机制来开发自己**的闭环系统。它以一个标准的 Harness Package（`self-dev-harness/`）的形式存在，安装后 Lumos 就获得了"自我迭代开发"的能力。

```
调研差距(对标 Claude Code)
        │
        ▼
   生成改进方案
        │
        ▼
 IM 通知架构师(Telegram)
        │
        ▼
   等待审批 ←── 架构师审查方案
        │
        ▼
   实现代码变更
        │
        ▼
   自动化测试
        │
        ▼
  提 PR 到 GitHub
        │
        ▼
  等待 Code Review
        │                      ┌──────────────────┐
        └─────────────────────→│  下一个迭代循环   │
                               └──────────────────┘
```

### 1.2 为什么要做

**现状问题：** Lumos 对标 Claude Code 还有大量功能差距（sandbox、permission model、context management、hooks 等），目前完全依赖人工识别和实现。

**三重验证价值：**
1. **功能价值** — 自动化差距识别 → 方案生成 → 代码实现，加速演进
2. **架构验证** — self-dev-harness 本身是 Harness Package，验证框架可扩展性
3. **信任建立** — Lumos 用自己的 Harness 开发自己 = dogfooding = 框架设计正确的最有力证明

### 1.3 核心创新点

| 创新点 | 说明 |
|---|---|
| Self-Hosting | Agent 使用自己的扩展机制增强自己 |
| 人机协同闭环 | 关键决策点由人把关，Agent 负责执行 |
| 短生命周期 Agent | 每阶段独立任务，状态持久化，调度器驱动 |
| Harness Dogfooding | 自开发能力以 Harness Package 打包 |

---

## 2. 两阶段关系图

### 2.1 依赖关系全景

```
╔═════════════════════════════════════════════════════════════════╗
║                   TWO-PHASE DEPENDENCY MAP                      ║
╠═════════════════════════════════════════════════════════════════╣
║                                                                  ║
║  ┌───────────────────────────────────────────────────────────┐  ║
║  │              阶段一：重构 Lumos 核心架构                   │  ║
║  │            (architecture-v2.md Phase 1-4)                  │  ║
║  │                                                            │  ║
║  │  ┌────────────────┐ ┌────────────────┐ ┌────────────────┐│  ║
║  │  │Interceptor     │ │Trajectory      │ │Harness         ││  ║
║  │  │Engine          │ │Logger          │ │Loader          ││  ║
║  │  │(L5:洋葱模型)   │ │(L6:行为记录)   │ │(Package系统)   ││  ║
║  │  │                │ │                │ │                ││  ║
║  │  │• 10 生命周期点 │ │• JSONL 结构化  │ │• HARNESS.yaml  ││  ║
║  │  │• BaseIntercept │ │• 异步写入      │ │• 5 目录加载    ││  ║
║  │  │• run_chain()   │ │• Replay 支持   │ │• CLI 管理      ││  ║
║  │  └──────┬─────────┘ └──────┬─────────┘ └──────┬─────────┘│  ║
║  │         │ 必须              │ 建议              │ 必须     │  ║
║  └─────────┼──────────────────┼──────────────────┼───────────┘  ║
║            │                  │                  │               ║
║            ▼                  ▼                  ▼               ║
║  ┌───────────────────────────────────────────────────────────┐  ║
║  │              阶段二：self-dev-harness/                     │  ║
║  │                                                            │  ║
║  │  ┌─────────────┐ ┌─────────────┐ ┌─────────────────────┐ │  ║
║  │  │Interceptors │ │   Tools     │ │      Skills         │ │  ║
║  │  │• 审批等待   │ │• gap_analyze│ │ • code_style        │ │  ║
║  │  │• 状态持久化 │ │• proposal   │ │ • test_writing      │ │  ║
║  │  │• trajectory │ │• pr_creator │ │                     │ │  ║
║  │  │             │ │• im_notifier│ │                     │ │  ║
║  │  └─────────────┘ └─────────────┘ └─────────────────────┘ │  ║
║  │  + prompts/  + config/                                    │  ║
║  └───────────────────────────────────────────────────────────┘  ║
║                                                                  ║
║  依赖：InterceptorEngine(必须) TrajectoryLogger(建议)           ║
║        HarnessLoader(必须)     Evaluator(不需要)                ║
╚═════════════════════════════════════════════════════════════════╝
```

### 2.2 为什么必须两阶段

没有阶段一的 InterceptorEngine → 无法实现审批等待/恢复（需要 on_stop + before_agent 拦截点）。没有 HarnessLoader → self-dev 能力不能以标准 Package 安装。阶段二验证阶段一——如果 self-dev-harness 正常工作，证明 Harness Package 系统的表达力足够。

---

## 3. self-dev-harness 目录结构

### 3.1 完整目录树

```
self-dev-harness/
├── HARNESS.yaml                     # Harness 清单
├── interceptors/
│   ├── pipeline_state.py            # 状态持久化
│   ├── approval_gate.py             # 审批等待/恢复
│   └── dev_trajectory.py            # 开发过程 trajectory 记录
├── tools/
│   ├── gap_analyzer.py              # 差距分析工具
│   ├── proposal_generator.py        # 改进方案生成
│   ├── code_implementer.py          # 代码实现编排
│   ├── test_runner.py               # 测试运行
│   ├── pr_creator.py                # PR 创建
│   └── im_notifier.py               # IM 通知（Telegram）
├── skills/
│   ├── code-style/SKILL.md          # Lumos 代码风格规范
│   └── test-writing/SKILL.md        # Lumos 测试编写规范
├── prompts/
│   └── self_dev_system.md           # self-dev 模式 system prompt
└── config/
    ├── pipeline.yaml                # 状态机配置
    └── targets.yaml                 # 对标目标和优先级
```

### 3.2 HARNESS.yaml

```yaml
name: "self-dev"
version: "0.1.0"
description: "Self-Development Pipeline — 让 Lumos 用 Harness 机制开发自己"

provides:
  interceptors:
    - path: interceptors/pipeline_state.py
      class: PipelineStateInterceptor
      config: { state_dir: ".lumos/pipeline" }
    - path: interceptors/approval_gate.py
      class: ApprovalGateInterceptor
      config: { telegram_chat_id: "6692588039", timeout_hours: 72 }
    - path: interceptors/dev_trajectory.py
      class: DevTrajectoryInterceptor
      config: { output_dir: ".lumos/pipeline/trajectories" }
  tools:
    - tools/gap_analyzer.py
    - tools/proposal_generator.py
    - tools/code_implementer.py
    - tools/test_runner.py
    - tools/pr_creator.py
    - tools/im_notifier.py
  skills:
    - skills/code-style/SKILL.md
    - skills/test-writing/SKILL.md
  prompts:
    system_append: prompts/self_dev_system.md
  config:
    path: config/pipeline.yaml

compose: layer
compatibility: { lumos: ">=0.6.0", python: ">=3.11" }
```

### 3.3 Interceptors

#### PipelineStateInterceptor — 状态持久化

实现"短生命周期 Agent + 长时间 Pipeline"的关键。Agent 随时可退出，下次从上次状态继续。

```python
class PipelineState:
    """持久化到 .lumos/pipeline/state.json"""
    
    status: str              # 状态机节点 (idle/researching/...)
    current_task_id: str     # 当前任务 ID
    current_task: dict       # 任务完整描述
    task_queue: list[dict]   # 待处理队列
    history: list[dict]      # 已完成历史
    error_count: int         # 连续错误计数
    
    def save(self) -> None: ...
    def enqueue_task(self, task: dict) -> None: ...
    def dequeue_task(self) -> dict | None: ...
    def complete_current_task(self, result: dict) -> None: ...
    def record_error(self) -> int: ...


class PipelineStateInterceptor(BaseInterceptor):
    name = "pipeline-state"
    priority = 5  # 外层
    
    async def before_agent(self, ctx, proceed):
        """加载 state → ctx.metadata['pipeline_state']"""
    
    async def after_agent(self, ctx, proceed):
        """写回磁盘"""
    
    async def post_tool_use(self, result, proceed):
        """state_changed 时立即保存"""
```

state.json 示例：

```json
{
  "status": "awaiting_approval",
  "current_task_id": "gap-2026-04-05-context-mgmt",
  "current_task": {
    "type": "feature_gap",
    "dimension": "context_management",
    "title": "实现 auto_compact 上下文压缩",
    "priority_score": 0.85
  },
  "task_queue": [
    {"type": "feature_gap", "dimension": "permissions", "priority_score": 0.72}
  ],
  "history": [],
  "error_count": 0,
  "last_updated": 1712345678.0
}
```

#### ApprovalGateInterceptor — 审批等待/恢复

审批是异步的。Agent 发通知后退出，审批到达后调度器重启 Agent。

```python
class ApprovalGateInterceptor(BaseInterceptor):
    name = "approval-gate"
    priority = 10
    
    async def before_agent(self, ctx, proceed):
        """启动时检查审批：
        - awaiting_approval + 审批文件存在 → approved
        - awaiting_review + 审批文件存在 → merged  
        - 超时 → timed_out
        """
```

审批文件格式 (`.lumos/pipeline/approvals/{task_id}.json`)：

```json
{
  "approved": true,
  "reviewer": "Snape",
  "comment": "LGTM, 注意兼容性",
  "timestamp": 1712345678.0
}
```

#### DevTrajectoryInterceptor — 开发过程记录

继承 TrajectoryLogger，附加 pipeline 上下文（task_id、status）到每条 JSONL 事件。

### 3.4 Tools

| 工具 | 功能 | 输入 | 输出 |
|---|---|---|---|
| `analyze_gap` | 识别 Lumos vs Claude Code 差距 | dimension, depth | 差距报告 + 优先级排序 |
| `generate_proposal` | 为差距生成改进方案 | gap 对象, style | Proposal 结构 |
| `implement_code` | 根据方案实现代码变更 | task_id | 变更文件列表 + git commit |
| `run_tests` | 运行测试验证变更 | scope (affected/full) | 通过/失败 + 详情 |
| `create_pr` | 创建 GitHub PR | task_id, title, body | PR URL |
| `notify_architect` | Telegram 通知架构师 | type, content, task_id | 发送状态 |

**关键工具签名：**

```python
# gap_analyzer.py
async def _analyze_gap(tool_call_id, params, **kwargs) -> AgentToolResult:
    """params: {dimension: str, depth: str, update_cache: bool}"""

# proposal_generator.py  
async def _generate_proposal(tool_call_id, params, **kwargs) -> AgentToolResult:
    """params: {gap: dict, style: str}
    输出 Proposal 结构（见 3.4.1）"""

# code_implementer.py
async def _implement_code(tool_call_id, params, **kwargs) -> AgentToolResult:
    """流程：读方案 → 创建 branch → 逐步实现 → commit"""

# pr_creator.py
async def _create_pr(tool_call_id, params, **kwargs) -> AgentToolResult:
    """流程：git push → gh pr create → 返回 URL"""

# im_notifier.py
async def _notify(tool_call_id, params, **kwargs) -> AgentToolResult:
    """Telegram Bot API: POST /sendMessage"""
```

**Proposal 数据结构：**

```python
@dataclass
class Proposal:
    task_id: str                    # "gap-2026-04-05-context-mgmt"
    title: str                      # "实现 auto_compact 上下文压缩"
    dimension: str                  # "context_management"
    summary: str                    # 一段话概述
    affected_files: list[str]       # 需修改的文件
    new_files: list[str]            # 需新建的文件
    implementation_steps: list[str] # 实现步骤
    test_plan: str                  # 测试方案
    estimated_effort: str           # "low" | "medium" | "high"
    risk_assessment: str            # 风险评估
    backward_compatible: bool       # 是否向后兼容
    depends_on: list[str]           # 依赖的其他 task_id
```

### 3.5 Skills / Prompts / Config

**code-style/SKILL.md** — 规范纯函数优于有状态类、组合优于继承、Protocol 接口、向后兼容、Python 3.11+ type hints 等。

**test-writing/SKILL.md** — 规范 pytest + pytest-asyncio、不 mock LLM（用 stream_fn 注入）、重点测试 interceptor 链和 harness 加载。

**self_dev_system.md** — 注入 self-dev 模式 prompt：使用 tools 的工作流、每次只处理一个差距、遵循 code-style skill、等待人类审批。

**pipeline.yaml** — 状态机配置（详见第 4 节）。

**targets.yaml** — 对标 Claude Code 的具体能力清单和优先级权重。

---

## 4. Pipeline 状态机

### 4.1 状态转换图

```
                     ┌──────────────────────────────────────┐
                     │                                      │
                     ▼                                      │
              ┌──────────┐                                  │
              │   idle   │ ←──────────────────────────┐     │
              └────┬─────┘                            │     │
                   │ trigger: cron/manual              │     │
                   │ action: dequeue or analyze        │     │
                   ▼                                   │     │
          ┌─────────────────┐                         │     │
          │  researching    │                         │     │
          │                 │                         │     │
          │ • 调用 gap_ana- │                         │     │
          │   lyzer 分析差距│                         │     │
          │ • 选择最高优先  │                         │     │
          │   级差距项      │                         │     │
          └────────┬────────┘                         │     │
                   │ gap identified                    │     │
                   ▼                                   │     │
       ┌───────────────────────┐                      │     │
       │   proposal_ready      │                      │     │
       │                       │                      │     │
       │ • 调用 proposal_gen   │                      │     │
       │ • 生成改进方案        │                      │     │
       │ • 保存到 proposals/   │                      │     │
       └───────────┬───────────┘                      │     │
                   │ proposal saved                    │     │
                   │ action: notify_architect           │     │
                   ▼                                   │     │
     ┌──────────────────────────┐                     │     │
     │   awaiting_approval      │ ← Agent 退出        │     │
     │                          │   等待外部事件       │     │
     │ • IM 通知已发送          │                     │     │
     │ • 审批文件不存在         │                     │     │
     │ • 超时: 72h → timed_out  │ ──→ timed_out ──→ idle  │
     └──────────┬───────────────┘                     │     │
                │ approval file created               │     │
                ▼                                     │     │
         ┌──────────────┐                             │     │
         │   approved   │                             │     │
         │              │                             │     │
         │ • 读取审批内 │                             │     │
         │   容和批注   │                             │     │
         └──────┬───────┘                             │     │
                │                                     │     │
                ▼                                     │     │
      ┌──────────────────┐                            │     │
      │  implementing    │                            │     │
      │                  │                            │     │
      │ • 创建 feature   │                            │     │
      │   branch         │                            │     │
      │ • 调用 implement │                            │     │
      │   _code 工具     │                            │     │
      │ • 逐步实现方案   │                            │     │
      └────────┬─────────┘                            │     │
               │ code written                         │     │
               ▼                                      │     │
        ┌─────────────┐                               │     │
        │   testing   │                               │     │
        │             │                               │     │
        │ • run_tests │                               │     │
        │   (affected │                               │     │
        │   + full)   │                               │     │
        └──────┬──────┘                               │     │
               │                                      │     │
               ├─── tests failed ──→ implementing     │     │
               │    (retry, max 3)   (修复后重试)     │     │
               │                                      │     │
               │ tests passed                         │     │
               ▼                                      │     │
       ┌────────────────┐                             │     │
       │   pr_created   │                             │     │
       │                │                             │     │
       │ • git push     │                             │     │
       │ • gh pr create │                             │     │
       │ • notify IM    │                             │     │
       └───────┬────────┘                             │     │
               │                                      │     │
               ▼                                      │     │
   ┌─────────────────────────┐                        │     │
   │   awaiting_review       │ ← Agent 退出           │     │
   │                         │   等待外部事件          │     │
   │ • PR URL 已发送         │                        │     │
   │ • 等待 review 审批文件  │                        │     │
   │ • 超时: 72h → timed_out │ ──→ timed_out ──→ idle │     │
   └──────────┬──────────────┘                        │     │
              │ review approval file created          │     │
              ▼                                       │     │
        ┌───────────┐                                 │     │
        │  merged   │                                 │     │
        │           │                                 │     │
        │ • 记录历史│                                 │     │
        │ • 清理临时│                                 │     │
        │   文件    │                                 │     │
        └─────┬─────┘                                 │     │
              │                                       │     │
              └───────────────────────────────────────┘     │
                                                            │
                     error (任意状态) ──────────────────────┘
                       • error_count < 3: retry 当前状态
                       • error_count >= 3: → idle + 报警
```

### 4.2 状态定义表

| 状态 | 入口条件 | 出口条件 | 超时处理 | Agent 行为 |
|---|---|---|---|---|
| `idle` | 初始状态 / 上一任务完成 / 错误恢复 | 有任务待处理 | 无 | 检查队列或执行新分析 |
| `researching` | 从 idle 触发 | gap 分析完成，选出最高优先级 | 30min → error | 调用 analyze_gap |
| `proposal_ready` | gap 已选定 | proposal 已生成并保存 | 30min → error | 调用 generate_proposal |
| `awaiting_approval` | proposal 已保存，IM 已通知 | 审批文件出现 | 72h → timed_out | Agent 退出等待 |
| `approved` | 审批文件存在且 approved=true | 开始实现 | 无 | 读取审批批注 |
| `implementing` | 方案已审批 | 代码变更完成 | 2h → error | 调用 implement_code |
| `testing` | 代码已写完 | 测试全部通过 | 30min → error | 调用 run_tests |
| `pr_created` | 测试通过，PR 已创建 | PR URL 已通知 | 无 | 调用 create_pr + notify |
| `awaiting_review` | PR 已创建 | review 审批文件出现 | 72h → timed_out | Agent 退出等待 |
| `merged` | review 通过 | 历史已记录 | 无 | 清理 → idle |
| `timed_out` | 审批/review 超时 | 回到 idle | 无 | 发送超时通知 |
| `error` | 任意状态异常 | error_count < 3 重试 / >= 3 回 idle | 无 | 重试或报警 |

### 4.3 config/pipeline.yaml

```yaml
state_machine:
  initial: idle
  
  transitions:
    idle_to_researching:
      from: idle
      to: researching
      trigger: "task_available or cron"
    
    researching_to_proposal:
      from: researching
      to: proposal_ready
      trigger: "gap_selected"
      timeout_minutes: 30
    
    proposal_to_awaiting:
      from: proposal_ready
      to: awaiting_approval
      trigger: "proposal_saved and notification_sent"
      timeout_minutes: 30
    
    awaiting_to_approved:
      from: awaiting_approval
      to: approved
      trigger: "approval_file_exists"
      timeout_hours: 72
      timeout_action: timed_out
    
    approved_to_implementing:
      from: approved
      to: implementing
      trigger: "approval_read"
    
    implementing_to_testing:
      from: implementing
      to: testing
      trigger: "code_committed"
      timeout_minutes: 120
    
    testing_to_pr:
      from: testing
      to: pr_created
      trigger: "all_tests_passed"
      on_failure: implementing  # 退回实现，修复后重试
      max_retries: 3
      timeout_minutes: 30
    
    pr_to_awaiting_review:
      from: pr_created
      to: awaiting_review
      trigger: "pr_url_sent"
    
    awaiting_review_to_merged:
      from: awaiting_review
      to: merged
      trigger: "review_approval_exists"
      timeout_hours: 72
      timeout_action: timed_out
    
    merged_to_idle:
      from: merged
      to: idle
      trigger: "history_recorded"

  error_policy:
    max_consecutive_errors: 3
    on_max_errors: "reset_to_idle_and_alert"
    retry_delay_seconds: 60

scheduling:
  mode: "hybrid"  # cron + event
  cron: "0 10 * * 1-5"  # 工作日每天 10:00
  event_sources:
    - type: "file_watch"
      path: ".lumos/pipeline/approvals/"
      pattern: "*.json"
```

---

## 5. Gap Analyzer 设计

### 5.1 工作原理

Gap Analyzer 采用"本地静态扫描 + 远程数据获取 + 差距计算"三步走：

```
┌────────────────────────────────────────────────────────────┐
│                   Gap Analyzer 工作流                       │
│                                                             │
│  Step 1: 扫描 Lumos 能力                                    │
│  ┌─────────────────────────────────────────────────────┐   │
│  │ _scan_lumos_capabilities()                           │   │
│  │                                                     │   │
│  │ • 读 packages/server/tools/lumos_tools.py           │   │
│  │   → 已注册的 tool 名称列表                          │   │
│  │ • 读 core/agent_loop.py                             │   │
│  │   → loop 特性（是否有 interceptor 支持）             │   │
│  │ • 读 agents/mode_manager.py                         │   │
│  │   → 权限模型类型                                    │   │
│  │ • 读 skills/ 目录                                   │   │
│  │   → skill 系统能力                                  │   │
│  │ • 检查 interceptor/ 目录是否存在                    │   │
│  └─────────────────────────────────────────────────────┘   │
│                           │                                 │
│                           ▼                                 │
│  Step 2: 获取 Claude Code 能力基准                          │
│  ┌─────────────────────────────────────────────────────┐   │
│  │ _fetch_claude_code_capabilities()                    │   │
│  │                                                     │   │
│  │ 来源 1: 本地缓存                                     │   │
│  │   .lumos/pipeline/cache/claude_code_caps.json        │   │
│  │   (TTL: 7 天)                                       │   │
│  │                                                     │   │
│  │ 来源 2: 官方文档 (web_fetch)                         │   │
│  │   https://docs.anthropic.com/en/docs/claude-code    │   │
│  │                                                     │   │
│  │ 来源 3: GitHub 仓库分析                              │   │
│  │   github.com/anthropics/claude-code → CHANGELOG     │   │
│  │   → 提取最近的功能更新                               │   │
│  └─────────────────────────────────────────────────────┘   │
│                           │                                 │
│                           ▼                                 │
│  Step 3: 计算差距并排优先级                                  │
│  ┌─────────────────────────────────────────────────────┐   │
│  │ _compute_gaps()                                      │   │
│  │                                                     │   │
│  │ 对每个维度：                                         │   │
│  │ gap_severity = 缺失特性数 / Claude Code 总特性数     │   │
│  │ priority_score = gap_severity × dimension_weight    │   │
│  │                                                     │   │
│  │ 最终排序：按 priority_score 降序                     │   │
│  └─────────────────────────────────────────────────────┘   │
└────────────────────────────────────────────────────────────┘
```

### 5.2 对比维度详细定义

```python
COMPARISON_DIMENSIONS = {
    "tools": {
        "weight": 1.0,
        "claude_code_tools": [
            "Read", "Write", "Edit", "MultiEdit",
            "Bash", "Glob", "Grep", "LS",
            "TodoRead", "TodoWrite",
            "WebFetch", "WebSearch",
            "NotebookRead", "NotebookEdit",
        ],
        "lumos_equivalent": {
            "read_file": "Read",
            "write_file": "Write",
            "edit_file": "Edit",       # partial — 无 MultiEdit
            "bash": "Bash",
            "glob": "Glob",
            "grep": "Grep",
            # 缺: LS, NotebookRead, NotebookEdit
        },
    },
    
    "context_management": {
        "weight": 0.9,
        "claude_code_features": [
            "auto_compact",            # token 超限自动压缩 + 摘要
            "CLAUDE.md_hierarchy",     # project > global > cwd 三级加载
            "init_context",            # 首次进入目录自动探索
            "conversation_summary",    # 长对话自动摘要
        ],
        "lumos_status": {
            "auto_compact": "missing",
            "CLAUDE.md_hierarchy": "partial",  # 只有 project 级
            "init_context": "missing",
            "conversation_summary": "missing",
        },
    },
    
    "permissions": {
        "weight": 0.8,
        "claude_code_features": [
            "per_tool_approval",       # 首次使用危险工具需确认
            "allowlist_dirs",          # 信任目录白名单
            "allowlist_commands",      # 信任命令白名单
            "session_scoped",          # 本次会话内记住权限
            "settings_json_auto",      # settings.json 中预先声明
        ],
        "lumos_status": {
            "per_tool_approval": "missing",
            "allowlist_dirs": "missing",
            "allowlist_commands": "missing",
            "session_scoped": "missing",
            "settings_json_auto": "missing",
        },
    },
    
    "hooks": {
        "weight": 0.6,
        "claude_code_features": [
            "PreToolUse",
            "PostToolUse",
            "Notification",
            "Stop",
            "SubagentStop",
        ],
        "lumos_status": {
            "PreToolUse": "missing",   # 阶段一 InterceptorEngine 会实现
            "PostToolUse": "missing",
            "Notification": "missing",
            "Stop": "missing",
            "SubagentStop": "missing",
        },
    },
    
    "editing": {
        "weight": 0.8,
        "claude_code_features": [
            "unified_diff_edit",       # 支持 unified diff 格式输入
            "multi_file_edit",         # 单 tool call 编辑多文件
            "search_replace_edit",     # 精确搜索替换
            "auto_lint_after_edit",    # 编辑后自动 lint
        ],
        "lumos_status": {
            "unified_diff_edit": "missing",
            "multi_file_edit": "missing",
            "search_replace_edit": "partial",  # edit_file 支持但不稳定
            "auto_lint_after_edit": "missing",
        },
    },
    
    "mcp": {
        "weight": 0.4,
        "claude_code_features": [
            "mcp_server_discovery",    # 自动发现 MCP server
            "mcp_tool_registration",   # MCP tool 注册给 LLM
            "mcp_resource_access",     # 访问 MCP 资源
            "stdio_transport",         # stdio 传输
            "sse_transport",           # SSE 传输
        ],
        "lumos_status": {
            "mcp_server_discovery": "missing",
            "mcp_tool_registration": "missing",
            "mcp_resource_access": "missing",
            "stdio_transport": "missing",
            "sse_transport": "missing",
        },
    },
}
```

### 5.3 差距报告格式

```
## Lumos vs Claude Code 差距分析报告
生成时间: 2026-04-05 10:30

### 优先级排序（按 priority_score 降序）

1. context_management  score=0.72  effort=high  impact=critical
   缺失：auto_compact, init_context, conversation_summary
   建议：先实现 auto_compact（最高 ROI，token 超限是用户痛点）

2. permissions  score=0.64  effort=medium  impact=high
   缺失：per_tool_approval, allowlist_dirs, session_scoped
   建议：实现 per_tool_approval + session_scoped（最小可用权限模型）

3. tools (editing)  score=0.60  effort=medium  impact=high
   缺失：unified_diff_edit, multi_file_edit, auto_lint_after_edit
   建议：实现 unified_diff_edit（是 MultiEdit 的前提）

4. hooks  score=0.48  effort=low  impact=medium
   缺失：PreToolUse, PostToolUse, Stop, SubagentStop
   注：阶段一 InterceptorEngine 已规划，此项可能很快消除

5. mcp  score=0.32  effort=very_high  impact=medium
   缺失：全部 MCP 协议支持
   建议：暂时推迟，等 MCP 生态更成熟

### 总体评估
Lumos 覆盖 Claude Code 核心功能约 45%
最高价值 Quick Wins：context_management + permissions
长期差距：MCP（生态依赖，非技术问题）
```

---

## 6. 调度器设计

### 6.1 设计思路

Pipeline 不需要一个"永不停止"的长进程。调度器的职责只是**在正确的时机启动短生命周期的 Agent**。

```
调度器 (Orchestrator)
│
├── Trigger 1: cron (每天定时)
│   └── 检查 pipeline state
│       ├── idle → 启动 Agent (researching)
│       └── 非 idle → 检查是否可以推进 (超时等)
│
├── Trigger 2: file watch (实时)
│   └── .lumos/pipeline/approvals/ 目录出现新 .json 文件
│       └── 启动 Agent (继续 awaiting_approval/awaiting_review)
│
└── Trigger 3: manual
    └── lumos self-dev run
        └── 立即启动 Agent
```

### 6.2 Orchestrator 实现

```python
"""lumos/self_dev/orchestrator.py"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from pathlib import Path
from typing import Optional
import subprocess

logger = logging.getLogger(__name__)


class SelfDevOrchestrator:
    """Self-Dev Pipeline 调度器
    
    职责：
    1. cron 定时触发
    2. 文件监听触发（审批文件出现）
    3. 手动触发
    4. 错误恢复
    """
    
    def __init__(
        self,
        project_root: str = "/Users/snapek/github/lumos",
        state_dir: str = ".lumos/pipeline",
        cron_schedule: str = "0 10 * * 1-5",  # 工作日 10:00
    ):
        self._root = Path(project_root)
        self._state_dir = self._root / state_dir
        self._approvals_dir = self._state_dir / "approvals"
        self._state_file = self._state_dir / "state.json"
        self._running = False
    
    # ── 状态读取 ──────────────────────────────────────────────────
    
    def read_state(self) -> dict:
        if self._state_file.exists():
            with self._state_file.open() as f:
                return json.load(f)
        return {"status": "idle"}
    
    def should_start_agent(self) -> bool:
        """判断是否应该启动 Agent"""
        state = self.read_state()
        status = state.get("status", "idle")
        
        # 这些状态需要 Agent 介入
        actionable = {
            "idle",             # 可以开始新的分析
            "approved",         # 审批通过，可以实现
            "implementing",     # 实现中断，需要继续
            "testing",          # 测试中断，需要继续
        }
        
        # 这些状态等待外部事件（不主动启动）
        waiting = {
            "awaiting_approval",
            "awaiting_review",
        }
        
        if status in actionable:
            return True
        if status in waiting:
            # 检查是否有审批文件出现
            return self._has_new_approval(state.get("current_task_id"))
        
        return False
    
    def _has_new_approval(self, task_id: Optional[str]) -> bool:
        if not task_id:
            return False
        approval_file = self._approvals_dir / f"{task_id}.json"
        return approval_file.exists()
    
    # ── Agent 启动 ─────────────────────────────────────────────────
    
    async def launch_agent(self) -> int:
        """启动 self-dev Agent
        
        Returns:
            exit code (0=success, 非0=error)
        """
        cmd = [
            "python", "-m", "lumos.cli",
            "--harness", "self-dev",
            "--mode", "build",
            "--message", "继续 self-dev pipeline，从当前状态推进",
        ]
        
        logger.info(f"Launching self-dev agent: {' '.join(cmd)}")
        
        result = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=str(self._root),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        
        stdout, stderr = await result.communicate()
        
        if result.returncode != 0:
            logger.error(f"Agent exited with code {result.returncode}")
            logger.error(stderr.decode())
        
        return result.returncode
    
    # ── 文件监听 ──────────────────────────────────────────────────
    
    async def watch_approvals(self) -> None:
        """监听审批目录，有新文件时触发 Agent"""
        self._approvals_dir.mkdir(parents=True, exist_ok=True)
        known_files = set(self._approvals_dir.glob("*.json"))
        
        while self._running:
            await asyncio.sleep(10)  # 每 10 秒检查一次
            current_files = set(self._approvals_dir.glob("*.json"))
            new_files = current_files - known_files
            
            if new_files:
                logger.info(f"New approval files detected: {new_files}")
                if self.should_start_agent():
                    await self.launch_agent()
                known_files = current_files
    
    # ── Cron ──────────────────────────────────────────────────────
    
    async def run_cron(self) -> None:
        """运行 cron 调度（简化版：每隔 N 秒检查）
        
        生产环境建议使用 systemd timer 或 launchd plist
        """
        while self._running:
            if self.should_start_agent():
                await self.launch_agent()
            # 每小时检查一次（生产中用 cron 触发，这里是 fallback）
            await asyncio.sleep(3600)
    
    # ── 主入口 ────────────────────────────────────────────────────
    
    async def run(self) -> None:
        """启动调度器（cron + file watch 并行）"""
        self._running = True
        logger.info("SelfDevOrchestrator started")
        
        await asyncio.gather(
            self.run_cron(),
            self.watch_approvals(),
        )
    
    async def run_once(self) -> int:
        """手动触发一次（用于测试和调试）"""
        return await self.launch_agent()
    
    def stop(self) -> None:
        self._running = False
```

### 6.3 生产部署：launchd plist（macOS）

```xml
<!-- ~/Library/LaunchAgents/com.lumos.self-dev.plist -->
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>com.lumos.self-dev</string>
  
  <key>ProgramArguments</key>
  <array>
    <string>/usr/bin/python3</string>
    <string>-m</string>
    <string>lumos.self_dev.orchestrator</string>
    <string>--once</string>
  </array>
  
  <key>WorkingDirectory</key>
  <string>/Users/snapek/github/lumos</string>
  
  <!-- 每天工作日 10:00 触发 -->
  <key>StartCalendarInterval</key>
  <array>
    <dict>
      <key>Weekday</key><integer>1</integer>
      <key>Hour</key><integer>10</integer>
      <key>Minute</key><integer>0</integer>
    </dict>
  </array>
  
  <!-- 文件出现时也触发（审批文件） -->
  <key>WatchPaths</key>
  <array>
    <string>/Users/snapek/github/lumos/.lumos/pipeline/approvals</string>
  </array>
  
  <key>StandardOutPath</key>
  <string>/Users/snapek/github/lumos/.lumos/pipeline/logs/orchestrator.log</string>
  <key>StandardErrorPath</key>
  <string>/Users/snapek/github/lumos/.lumos/pipeline/logs/orchestrator.err</string>
</dict>
</plist>
```

安装：`launchctl load ~/Library/LaunchAgents/com.lumos.self-dev.plist`

### 6.4 错误恢复策略

```
错误发生时：
  error_count += 1
  
  if error_count < 3:
    记录错误日志
    等待 60 秒
    重试当前状态
  
  else:
    发送 Telegram 告警
    status → idle
    error_count = 0
    等待人工介入

超时处理：
  每次 Agent 启动时检查当前任务的创建时间
  如果超过状态配置的 timeout → timed_out → 通知 → idle
```

---

## 7. IM 集成

### 7.1 架构概览

```
                  Lumos Agent
                      │
                      │ im_notifier tool
                      ▼
            Telegram Bot API
          (api.telegram.org)
                      │
                      │ 推送消息
                      ▼
              Snape 的 Telegram
              (ID: 6692588039)
                      │
                      │ 回复 /approve 或 /reject
                      ▼
         Telegram Bot 轮询或 Webhook
                      │
                      │ 写入审批文件
                      ▼
     .lumos/pipeline/approvals/{task_id}.json
                      │
                      │ file watch 触发
                      ▼
              SelfDevOrchestrator
              启动下一阶段 Agent
```

### 7.2 通知消息格式

**审批请求（proposal_ready → awaiting_approval）：**

```
🔔 Lumos Self-Dev: 方案待审批

📋 任务 ID: gap-2026-04-05-context-mgmt
📌 标题: 实现 auto_compact 上下文压缩
🏷 维度: context_management
⏱ 预计工作量: medium
✅ 向后兼容: 是

📝 方案摘要:
在 agent_loop 的 before_model 拦截点实现 token 计数（使用 tiktoken），
超过 80% 上下文窗口时触发 sliding window 压缩策略：
保留最近 20 轮消息，对更早的 tool_result 进行摘要压缩。

📁 影响文件:
• packages/server/interceptor/builtins/context_compressor.py (新建)
• packages/server/agents/lumos_agent.py (修改，注入 interceptor)
• packages/server/core/agent_loop.py (修改，interceptor_engine 参数)

🧪 测试方案:
单元测试 context_compressor 的压缩逻辑；
集成测试 agent_loop 传入 interceptor_engine 的向后兼容性。

---
回复以下命令操作：
✅ /approve gap-2026-04-05-context-mgmt
❌ /reject gap-2026-04-05-context-mgmt 原因
```

**PR 通知（pr_created）：**

```
🔀 Lumos Self-Dev: PR 已创建

📋 任务: 实现 auto_compact 上下文压缩
🔗 PR URL: https://github.com/snapek/lumos/pull/42
📊 变更: +285 行 / -12 行 / 2 个新文件
✅ 测试: 全部通过 (42/42)

---
回复以下命令 Review：
✅ /approve gap-2026-04-05-context-mgmt
❌ /reject gap-2026-04-05-context-mgmt 需要修改
```

**状态更新 / 错误告警：**

```
⚠️ Lumos Self-Dev: 需要注意

任务: 实现 auto_compact 上下文压缩
状态: testing
错误: 测试失败 3 次，已自动回到 idle

错误详情:
  FAILED packages/tests/test_context_compressor.py::test_compress_sliding_window
  AssertionError: 压缩后消息数量不正确

请手动检查后用 /resume gap-2026-04-05-context-mgmt 恢复。
```

### 7.3 Telegram Bot 命令处理

Telegram Bot 需要处理以下命令，将审批写入文件：

```python
"""lumos/self_dev/telegram_bot.py"""

import json
import time
from pathlib import Path
import asyncio
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes


APPROVALS_DIR = Path("/Users/snapek/github/lumos/.lumos/pipeline/approvals")

async def approve_command(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """处理 /approve {task_id} [comment]"""
    args = ctx.args
    if not args:
        await update.message.reply_text("用法: /approve {task_id} [comment]")
        return
    
    task_id = args[0]
    comment = " ".join(args[1:]) if len(args) > 1 else "LGTM"
    
    # 写入审批文件
    approval_file = APPROVALS_DIR / f"{task_id}.json"
    approval_data = {
        "approved": True,
        "reviewer": update.effective_user.username,
        "comment": comment,
        "timestamp": time.time(),
    }
    with approval_file.open("w") as f:
        json.dump(approval_data, f, ensure_ascii=False)
    
    await update.message.reply_text(f"✅ 已批准任务: {task_id}")


async def reject_command(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """处理 /reject {task_id} [reason]"""
    args = ctx.args
    if not args:
        await update.message.reply_text("用法: /reject {task_id} [reason]")
        return
    
    task_id = args[0]
    reason = " ".join(args[1:]) if len(args) > 1 else "需要修改"
    
    approval_file = APPROVALS_DIR / f"{task_id}.json"
    approval_data = {
        "approved": False,
        "reviewer": update.effective_user.username,
        "comment": reason,
        "timestamp": time.time(),
    }
    with approval_file.open("w") as f:
        json.dump(approval_data, f, ensure_ascii=False)
    
    await update.message.reply_text(f"❌ 已拒绝任务: {task_id}\n原因: {reason}")
```

### 7.4 Telegram Bot Token 配置

```python
# config/pipeline.yaml 中配置
telegram:
  bot_token_env: "LUMOS_TELEGRAM_BOT_TOKEN"
  chat_id: "6692588039"  # Snape 的 Telegram ID
```

---

## 8. 阶段一的最小依赖

阶段二（self-dev-harness）需要阶段一的以下具体模块才能运行：

### 8.1 必须的模块

#### InterceptorEngine — 必须

**为什么：** `PipelineStateInterceptor` 和 `ApprovalGateInterceptor` 都是 `BaseInterceptor` 子类，需要 `InterceptorEngine.run_chain()` 在生命周期点上执行它们。没有 InterceptorEngine，这些 interceptor 根本无法被调用。

**最小接口：**

```python
# lumos/interceptor/engine.py
class InterceptorEngine:
    def register(self, interceptor: BaseInterceptor) -> None: ...
    async def run_chain(self, event_name, initial_value, core_fn, **kwargs) -> Any: ...

# lumos/interceptor/base.py
class BaseInterceptor:
    name: str
    priority: int
    async def before_agent(self, ctx, proceed): return await proceed(ctx)
    async def after_agent(self, ctx, proceed): return await proceed(ctx)
    async def pre_tool_use(self, request, proceed): return await proceed(request)
    async def post_tool_use(self, result, proceed): return await proceed(result)
    async def on_stop(self, ctx, proceed): return await proceed(ctx)
    async def on_error(self, error, proceed): return await proceed(error)

# lumos/interceptor/types.py
class AgentContext:
    messages, tools, system_prompt, llm_config, metadata: dict

class ToolResult:
    tool_call_id, tool_name, content, is_error, metadata: dict
```

**agent_loop 改造（最小改动）：**

```python
# packages/server/core/agent_loop.py
async def agent_loop(
    messages, tools, llm_config, loop_config,
    stream_fn=None, abort_signal=None,
    get_steering_messages=None, get_follow_up_messages=None,
    # ★ 新增：可选，不传时行为完全不变
    interceptor_engine=None,
) -> EventStream[AgentEvent]:
    ...
```

#### HarnessLoader — 必须

**为什么：** self-dev-harness 需要被作为标准 Harness Package 安装和加载。没有 HarnessLoader，就无法从 `HARNESS.yaml` 加载 interceptors、tools、skills、prompts。

**最小接口：**

```python
# lumos/harness/loader.py
class HarnessLoader:
    def __init__(self, harness_path: Path | str): ...
    def load_interceptors(self) -> list[BaseInterceptor]: ...
    def load_tools(self) -> list[AgentTool]: ...
    def load_skills_dirs(self) -> list[Path]: ...
    def load_system_prompt_patch(self) -> str: ...
    def load_config(self) -> dict: ...
```

**LumosAgent 改造（最小改动）：**

```python
# packages/server/agents/lumos_agent.py
class LumosAgent:
    def __init__(self, ..., active_harness_path=None):
        ...
        if active_harness_path:
            loader = HarnessLoader(active_harness_path)
            engine = InterceptorEngine()
            for interceptor in loader.load_interceptors():
                engine.register(interceptor)
            self._interceptor_engine = engine
            self._extra_tools = loader.load_tools()
            self._system_prompt_patch = loader.load_system_prompt_patch()
```

### 8.2 建议的模块

#### TrajectoryLogger — 建议但非必须

`DevTrajectoryInterceptor` 继承自 `TrajectoryLogger`。如果 TrajectoryLogger 未实现，可以先用一个简单的 stub 代替：

```python
# 临时 stub（阶段二先用这个）
class TrajectoryLogger(BaseInterceptor):
    name = "trajectory-logger-stub"
    priority = 1
    # 所有方法都透传，等阶段一实现真正的 TrajectoryLogger 后替换
```

### 8.3 不需要的模块

#### Evaluator — 不需要

Self-dev pipeline 的"评估"由人类审批完成，不需要自动化的 Evaluator。Evaluator 是 architecture-v2 的 Phase 3 内容，可以在更晚的阶段再实现。

#### ShellInterceptor — 不需要

Self-dev-harness 的所有 interceptors 都用 Python class 实现，不使用 YAML shell 简写，因此不依赖 ShellInterceptor。

### 8.4 最小可运行条件（清单）

```
✅ InterceptorEngine
   - run_chain(event_name, initial_value, core_fn) 洋葱模型
   - register(interceptor)
   
✅ BaseInterceptor
   - 10 个生命周期点透传默认实现
   
✅ HarnessLoader  
   - load_interceptors(), load_tools()
   - load_skills_dirs(), load_system_prompt_patch()
   - load_config()
   
✅ agent_loop 增加 interceptor_engine 参数（向后兼容，默认 None）

✅ LumosAgent 支持 active_harness_path 初始化参数

⚠️ TrajectoryLogger（建议，可用 stub 代替）

❌ Evaluator（不需要）
❌ ShellInterceptor（不需要）
❌ OptimizationWorkspace（不需要）

---

## 9. 分阶段实施路线图

### 9.1 总体时间线

```
今天                                               跑通第一个完整循环
│                                                         │
▼                                                         ▼
├─── Step 1 ───┤── Step 2 ──┤─── Step 3 ───┤── Step 4 ──┤
│   (1-2天)    │  (2-3天)   │   (2-3天)    │  (1-2天)   │
│              │            │              │            │
│ Interceptor  │ Harness    │ self-dev-    │ 首轮       │
│ Engine       │ Loader     │ harness      │ Pipeline   │
│ + 基础类型   │ + agent    │ interceptors │ 运行       │
│              │ 改造       │ + tools      │            │
```

### 9.2 Step 1 — InterceptorEngine 基础设施（1-2 天）

**目标：** 让 agent_loop 支持 interceptor 注入，同时向后兼容。

**需要实现的文件：**

```
packages/server/
├── interceptor/
│   ├── __init__.py
│   ├── engine.py          # InterceptorEngine
│   ├── base.py            # BaseInterceptor（10 个生命周期点默认透传）
│   └── types.py           # AgentContext, ToolResult, ModelRequest 等数据类型
└── core/
    └── agent_loop.py      # 增加 interceptor_engine 可选参数（3 处改动）
```

**验收：**
- 传入 interceptor_engine=None 时，agent 行为与现在完全一致（现有测试全部通过）
- 传入一个 BaseInterceptor 子类（只透传），行为依然一致
- 传入一个在 `before_model` 打日志的 interceptor，能看到打印

**具体代码改动（agent_loop.py 的 3 处）：**

```python
# 改动 1：函数签名增加参数
async def agent_loop(
    ..., interceptor_engine=None
) -> EventStream[AgentEvent]:

# 改动 2：before_agent
if interceptor_engine:
    ctx = AgentContext(messages=messages, tools=tools, ...)
    ctx = await interceptor_engine.run_chain("before_agent", ctx, lambda c: c)

# 改动 3：LLM 调用前后
if interceptor_engine:
    request = ModelRequest(messages=messages, ...)
    request = await interceptor_engine.run_chain("before_model", request, lambda r: r)
    response = await interceptor_engine.run_wrap("wrap_model", request, _call_model)
    response = await interceptor_engine.run_chain("after_model", response, lambda r: r)
else:
    assistant_msg = await stream_fn(...)  # 原来的路径

# 改动 4：工具调用前后
if interceptor_engine:
    tool_req = ToolRequest(...)
    tool_req = await interceptor_engine.run_chain("pre_tool_use", tool_req, lambda r: r)
    tool_result = await interceptor_engine.run_wrap("wrap_tool", tool_req, _execute)
    tool_result = await interceptor_engine.run_chain("post_tool_use", tool_result, lambda r: r)
else:
    result = await tool.execute(...)  # 原来的路径
```

### 9.3 Step 2 — HarnessLoader + LumosAgent 改造（2-3 天）

**目标：** 让 Harness Package 可以被加载，LumosAgent 支持激活 harness。

**需要实现的文件：**

```
packages/server/
├── harness/
│   ├── __init__.py
│   └── loader.py          # HarnessLoader
└── agents/
    └── lumos_agent.py     # 增加 active_harness_path 支持
```

**HarnessLoader 实现要点：**

```python
class HarnessLoader:
    def __init__(self, harness_path): ...
    
    def load_interceptors(self) -> list[BaseInterceptor]:
        # 读 HARNESS.yaml → provides.interceptors
        # 动态 import Python 文件 → 找到指定 class → 实例化（传 config）
    
    def load_tools(self) -> list[AgentTool]:
        # 读 HARNESS.yaml → provides.tools
        # 动态 import → 找到 AgentTool 实例或工厂函数
    
    def load_skills_dirs(self) -> list[Path]:
        # 读 HARNESS.yaml → provides.skills → 返回目录列表
    
    def load_system_prompt_patch(self) -> str:
        # 读 HARNESS.yaml → provides.prompts.system_append
        # 返回文件内容
    
    def load_config(self) -> dict:
        # 读 HARNESS.yaml → provides.config.path → 返回 yaml 内容
```

**LumosAgent 改造要点：**

```python
class LumosAgent:
    def __init__(self, ..., active_harness_path: str | None = None):
        ...
        # 加载 harness
        self._interceptor_engine = None
        self._harness_extra_tools: list[AgentTool] = []
        self._system_prompt_patch = ""
        
        if active_harness_path:
            loader = HarnessLoader(active_harness_path)
            
            engine = InterceptorEngine()
            for interceptor in loader.load_interceptors():
                engine.register(interceptor)
            self._interceptor_engine = engine
            
            self._harness_extra_tools = loader.load_tools()
            self._system_prompt_patch = loader.load_system_prompt_patch()
            
            # 将 harness skills 加入 SkillManager 的搜索路径
            for skills_dir in loader.load_skills_dirs():
                self._skill_manager.add_search_dir(skills_dir)
    
    def _build_system_prompt(self) -> str:
        base = self.DEFAULT_SYSTEM_PROMPT + ...
        return base + self._system_prompt_patch  # 追加 harness prompt
    
    def _get_all_tools(self) -> list[AgentTool]:
        base_tools = create_tools_for_mode(self.mode_manager.current_mode)
        return base_tools + self._harness_extra_tools
```

**验收：**

```bash
# 安装 self-dev-harness 后，能看到 harness tools
lumos harness install ./self-dev-harness
lumos --harness self-dev --message "列出你可用的工具"
# 输出中应包含: analyze_gap, generate_proposal, notify_architect 等
```

### 9.4 Step 3 — self-dev-harness 实现（2-3 天）

**目标：** 实现 self-dev-harness 的所有组件。

**优先顺序：**

1. **pipeline_state.py** — 状态持久化（最基础，其他都依赖它）
2. **approval_gate.py** — 审批等待/恢复（核心机制）
3. **im_notifier.py** — Telegram 通知（让人工审批闭环）
4. **gap_analyzer.py** — 差距分析（pipeline 第一步）
5. **proposal_generator.py** — 方案生成
6. **code_implementer.py** — 代码实现（最复杂）
7. **test_runner.py** — 测试运行
8. **pr_creator.py** — PR 创建
9. **dev_trajectory.py** — 轨迹记录（最后加，不影响功能）

**验收（每个 tool 单独测试）：**

```bash
# 测试 gap_analyzer
python -c "
from self_dev_harness.tools.gap_analyzer import gap_analyzer_tool
import asyncio
result = asyncio.run(gap_analyzer_tool.execute('test-id', {'dimension': 'context_management', 'depth': 'overview'}))
print(result.content[0].text)
"

# 测试 im_notifier
python -c "
from self_dev_harness.tools.im_notifier import im_notifier_tool
import asyncio
result = asyncio.run(im_notifier_tool.execute('test-id', {'message_type': 'status_update', 'content': '测试消息', 'task_id': 'test-123'}))
print(result.content[0].text)
"
```

### 9.5 Step 4 — 首轮 Pipeline 运行（1-2 天）

**目标：** 跑通第一个完整的 gap → PR 循环。

**步骤：**

1. 安装 self-dev-harness：
   ```bash
   lumos harness install /path/to/self-dev-harness
   ```

2. 手动触发第一轮（跳过 cron，直接运行）：
   ```bash
   lumos --harness self-dev --message "开始 self-dev pipeline，分析 Lumos 与 Claude Code 的差距，选择优先级最高的一个，生成改进方案"
   ```

3. 验证 pipeline state 文件被正确写入：
   ```bash
   cat /Users/snapek/github/lumos/.lumos/pipeline/state.json
   ```

4. 验证 Telegram 通知已发送（查看 Snape 的 Telegram）

5. 回复 `/approve {task_id}` 审批

6. 验证 approval_gate 检测到审批文件，继续执行

7. 验证 PR 被创建（检查 GitHub）

**关键调试命令：**

```bash
# 查看当前 pipeline 状态
cat .lumos/pipeline/state.json | python3 -m json.tool

# 查看审批目录
ls -la .lumos/pipeline/approvals/

# 查看 trajectory 日志
ls -la .lumos/pipeline/trajectories/
cat .lumos/pipeline/trajectories/$(ls -t .lumos/pipeline/trajectories/ | head -1) | python3 -c "
import json, sys
for line in sys.stdin:
    ev = json.loads(line)
    print(f'{ev[\"event\"]:20} {ev.get(\"tool_name\", \"\")}')
"

# 手动写入审批文件（测试用）
echo '{"approved": true, "reviewer": "Snape", "comment": "test", "timestamp": '$(date +%s)'}' \
  > .lumos/pipeline/approvals/gap-test-123.json
```

---

## 10. Dogfooding 验证

### 10.1 验证标准

Dogfooding 的验证目标是：**跑通一个从 gap 识别到 PR 合并的完整循环**，证明 self-dev-harness 作为一个 Harness Package 能够正常工作。

### 10.2 验证用例：第一个 PR

选择一个具体的、低风险的差距项作为第一个验证用例：

**推荐：实现 `ls` 工具（最简单的 tool gap）**

```
Claude Code 有：LS tool
Lumos 缺少：LS tool

实现难度：低（不涉及架构改动，只需添加新工具）
验证价值：完整走通整个 pipeline 流程
```

**预期输出：**

```
1. gap_analyzer 识别到 tools 维度缺少 LS tool
2. generate_proposal 生成:
   title: "添加 ls 目录列表工具"
   affected_files: ["packages/server/tools/lumos_tools.py"]
   new_files: ["packages/server/tools/ls_tool.py"]
   implementation_steps: ["..."]
   estimated_effort: "low"
   
3. Telegram 发送审批请求 → Snape 收到通知

4. Snape 回复 /approve gap-xxx-ls-tool

5. approval_gate 检测到审批文件 → status: approved

6. code_implementer 创建 branch feat/gap-xxx-ls-tool
   → 实现 ls_tool.py
   → 修改 lumos_tools.py 注册新工具
   → git commit

7. test_runner 运行测试 → 全部通过

8. pr_creator 推送 branch → 创建 PR
   → Telegram 发送 PR URL

9. Snape 回复 /approve {task_id}（或直接在 GitHub 上 review）

10. merged → status: idle → 等待下一轮
```

### 10.3 验证矩阵

| 验证项 | 验证方法 | 预期结果 |
|---|---|---|
| HarnessLoader 加载 | `lumos harness inspect` | 显示 6 个 tools、3 个 interceptors |
| InterceptorEngine 注入 | 查看 trajectory JSONL | 有 `agent_start` / `tool_start` 事件 |
| PipelineState 持久化 | 查看 state.json | 状态正确更新 |
| ApprovalGate 等待 | Agent 退出后 state = awaiting | Agent 正常退出而不是卡住 |
| ApprovalGate 恢复 | 写入审批文件后重启 Agent | Agent 从 approved 状态继续 |
| gap_analyzer 分析 | 调用后查看输出 | 包含优先级排序的差距报告 |
| im_notifier 通知 | Snape Telegram 收到消息 | 消息格式正确，包含任务详情 |
| pr_creator 创建 PR | GitHub 上出现 PR | Branch 和 PR 都正确创建 |
| 完整循环 | 端到端测试 | gap → proposal → approved → code → PR |

### 10.4 观测手段

**实时观测（运行时）：**

```bash
# Terminal 1: 监控 pipeline 状态
watch -n 5 'cat .lumos/pipeline/state.json | python3 -m json.tool'

# Terminal 2: 实时查看 trajectory
tail -f .lumos/pipeline/trajectories/$(ls -t .lumos/pipeline/trajectories/ | head -1)

# Terminal 3: 运行 Agent
lumos --harness self-dev --message "开始 self-dev pipeline"
```

**事后分析：**

```python
# 分析 trajectory 日志
from lumos.trajectory.replay import TrajectoryReplay

replay = TrajectoryReplay(".lumos/pipeline/trajectories/latest.jsonl")
summary = replay.summary()
print(f"总轮数: {summary['turns']}")
print(f"工具调用: {summary['tool_calls']}")
print(f"耗时: {summary['duration_s']:.1f}s")
print(f"工具序列: {replay.tool_sequence()}")
```

### 10.5 成功标准

以下条件全部满足即视为验证通过：

1. ✅ `lumos harness install ./self-dev-harness` 成功，无报错
2. ✅ `lumos harness inspect` 显示所有 6 个 tools 和 3 个 interceptors
3. ✅ 运行后 `.lumos/pipeline/state.json` 被正确创建和更新
4. ✅ Telegram 收到审批请求通知
5. ✅ 回复 `/approve` 后 Agent 在下次启动时继续执行
6. ✅ GitHub 上出现包含代码变更的 PR
7. ✅ PR 的代码变更通过 `pytest` 测试
8. ✅ `.lumos/pipeline/trajectories/` 包含完整的 JSONL 轨迹

---

## 附录：关键文件路径索引

```
/Users/snapek/github/lumos/
├── packages/server/
│   ├── core/
│   │   ├── agent_loop.py         # ★ 需改造（interceptor_engine 参数）
│   │   ├── tool.py               # 无需改动
│   │   ├── types.py              # 无需改动
│   │   └── event_stream.py       # 无需改动
│   ├── agents/
│   │   ├── lumos_agent.py        # ★ 需改造（active_harness_path）
│   │   └── mode_manager.py       # 最小改动（config_overrides）
│   ├── interceptor/              # ★ 新建目录
│   │   ├── __init__.py
│   │   ├── engine.py             # InterceptorEngine
│   │   ├── base.py               # BaseInterceptor
│   │   └── types.py              # AgentContext, ToolResult 等
│   ├── harness/                  # ★ 新建目录
│   │   ├── __init__.py
│   │   └── loader.py             # HarnessLoader
│   └── skills/
│       └── manager.py            # 小改动（add_search_dir）
│
├── self-dev-harness/             # ★ 新建（Harness Package）
│   ├── HARNESS.yaml
│   ├── interceptors/
│   ├── tools/
│   ├── skills/
│   ├── prompts/
│   └── config/
│
├── .lumos/pipeline/              # 运行时自动创建
│   ├── state.json                # Pipeline 状态
│   ├── approvals/                # 审批文件
│   ├── proposals/                # 方案文件
│   └── trajectories/             # JSONL 日志
│
└── docs/
    ├── architecture-v2.md        # 阶段一架构设计
    └── self-dev-pipeline.md      # 本文档
```

---

*文档版本：v1.0-draft | 最后更新：2026-04-04*
