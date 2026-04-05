# yoyo-evolve 调研报告

> **调研时间**: 2026-04-04
> **调研目的**: 分析 yoyo-evolve 的自演进架构，识别可采纳到 Lumos 的设计模式
> **仓库**: https://github.com/yologdev/yoyo-evolve

---

## 一、项目概览

yoyo 是一个用 Rust 写的终端 coding agent，核心卖点是**自我演进**——从 200 行起步，通过 GitHub Actions cron 每 8 小时自主演化一次，35 天后长到 31,000+ 行、1,346 个测试、14 个模块。

**一句话定位**: "A Truman Show of a self-evolving AI coding agent. It writes its own code. Growing up in public."

**创建者**: [@yuanhao](https://x.com/yuanhao)（yologdev）

**关键数据**:
- 语言: Rust
- 代码规模: ~31,000 行，79+ 文件
- 测试: 1,346 个（82 个集成测试）
- 演化周期: 每 8 小时一次（cron 每小时触发，脚本内部控制频率）
- 社交周期: 每 4 小时一次（GitHub Discussions 自动参与）
- 模型: Claude Opus（演化）+ Claude Sonnet（社交），fallback 到智谱
- 成本: ~$3-8/session，~$300-750/月
- 工具: 8 个核心 tool + 55 个 slash command
- 提供商: 12 个（Anthropic/OpenAI/Google/Ollama/OpenRouter 等）
- 出生日期: 2026-02-28

---

## 二、架构详解

### 2.1 整体架构

```
┌─────────────────────────────────────────────────────┐
│              GitHub Actions (cron)                    │
│                                                      │
│  ┌──────────────────┐    ┌──────────────────┐       │
│  │ evolve.yml       │    │ social.yml        │       │
│  │ 每小时触发       │    │ 每 4h 触发        │       │
│  │ 8h 频率门控      │    │                   │       │
│  │ 3 次失败重试     │    │                   │       │
│  │ (15min/45min)    │    │                   │       │
│  └────────┬─────────┘    └────────┬──────────┘       │
│           │                       │                   │
│           ▼                       ▼                   │
│  ┌──────────────────┐    ┌──────────────────┐       │
│  │ evolve.sh        │    │ social.sh         │       │
│  │ (2036 行 bash)   │    │                   │       │
│  │                  │    │ 读 Discussions    │       │
│  │ Step 0: 赞助商   │    │ 回复/发帖        │       │
│  │ Step 1: 评估A1   │    │ 写 social_       │       │
│  │ Step 2: 规划A2   │    │ learnings.jsonl   │       │
│  │ Step 3: 实现     │    │                   │       │
│  │ Step 4: 回复Issue│    │                   │       │
│  │ Step 5: 写日志   │    │                   │       │
│  │ Step 6: 推送     │    │                   │       │
│  └────────┬─────────┘    └───────────────────┘       │
│           │ 调用自己的 binary                         │
│           ▼                                           │
│  ┌──────────────────────────────────────────┐        │
│  │          yoyo (Rust binary)               │        │
│  │  src/main.rs      — 入口 + agent 配置     │        │
│  │  src/hooks.rs     — Hook trait + Registry │        │
│  │  src/memory.rs    — 项目记忆              │        │
│  │  src/prompt.rs    — System prompt 组装    │        │
│  │  src/repl.rs      — REPL 循环            │        │
│  │  src/format.rs    — Markdown 渲染        │        │
│  │  src/git.rs       — Git 操作             │        │
│  │  src/commands*.rs — 55 个 slash 命令      │        │
│  │  src/docs.rs      — 文档查询             │        │
│  │  src/setup.rs     — 首次引导             │        │
│  └──────────────────────────────────────────┘        │
│                                                      │
│  ┌──────────────────────────────────────────┐        │
│  │ daily_diary.sh (synthesis job)            │        │
│  │ - 读 learnings.jsonl + social_learnings   │        │
│  │ - 时间加权压缩                            │        │
│  │ - 生成 active_learnings.md                │        │
│  │ - 生成 active_social_learnings.md         │        │
│  └──────────────────────────────────────────┘        │
└─────────────────────────────────────────────────────┘
```

### 2.2 演进循环（evolve.sh）完整流程

```
┌─────────────┐
│ cron 触发   │
└──────┬──────┘
       ▼
┌──────────────────────────┐     ┌──────────────┐
│ Step 0: 频率门控          │────→│ <8h? 退出    │
│ - 检查 last_session.txt   │     └──────────────┘
│ - 赞助商 GraphQL 查询     │
│ - 优先级排序              │
└──────┬───────────────────┘
       ▼
┌──────────────────────────┐
│ Step 1: A1 评估 Agent     │
│ - 输入: 源码 + JOURNAL    │
│   + Issues + learnings    │
│ - 输出: assessment.md     │
│ - 超时: TIMEOUT/2 秒      │
└──────┬───────────────────┘
       ▼
┌──────────────────────────┐
│ Step 2: A2 规划 Agent     │
│ - 输入: assessment        │
│   + 赞助商优先级          │
│ - 输出: 2-3 个 task JSON  │
│ - 超时: TIMEOUT/2 秒      │
└──────┬───────────────────┘
       ▼
┌──────────────────────────┐
│ Step 3: 逐个实现 task     │──→ 循环每个 task:
│                           │    ┌─────────────────────────┐
│                           │    │ yoyo -p "task" --yes    │
│                           │    │ cargo build + cargo test│
│                           │    │ 通过 → git commit       │
│                           │    │ 失败 → git reset --hard │
│                           │    └─────────────────────────┘
└──────┬───────────────────┘
       ▼
┌──────────────────────────┐
│ Step 4: 回复 Issues       │
│ - 读 agent-input 标签     │
│ - 评论进度/关闭           │
└──────┬───────────────────┘
       ▼
┌──────────────────────────┐
│ Step 5: 写 JOURNAL.md     │
│ + 追加 learnings.jsonl    │
└──────┬───────────────────┘
       ▼
┌──────────────────────────┐
│ Step 6: git push          │
└──────────────────────────┘
```

### 2.3 双 Agent 规划模式

yoyo 的规划不是一步完成的，而是**两个 Agent 串行**：

| Agent | 角色 | 输入 | 输出 | 模型 |
|---|---|---|---|---|
| **A1（评估）** | "你是 yoyo，一个自我演进的 coding agent" | 源码、JOURNAL、Issues、learnings、竞品对比 | assessment（当前状态 + 差距 + 优先级） | Opus |
| **A2（规划）** | 同上 + "基于评估，规划 2-3 个具体 task" | A1 的 assessment + 赞助商优先级 | JSON 格式的 task 列表 | Opus |

**关键设计**: A1 和 A2 各有 TIMEOUT/2 秒预算（默认各 600 秒）。评估和规划分开，避免规划受限于单次 context。

### 2.4 记忆系统

```
memory/
├── learnings.jsonl              # 只追加，永不压缩
│   格式: {"day": 31, "date": "2026-03-31", "source": "evolution",
│           "lesson": "...", "context": "..."}
│
├── social_learnings.jsonl       # 同上，来自社交互动
│
├── active_learnings.md          # synthesis job 每日生成
│   结构:
│   ## Recent (Last 2 Weeks)     ← 全文保留
│   ## Medium (2-8 Weeks Old)    ← 按主题聚合压缩
│   ## Foundational              ← 高度浓缩的核心原则
│
└── active_social_learnings.md   # 同上
```

**三层时间衰减**:
- **Recent** (< 2 周): 保留完整 Context + Lesson
- **Medium** (2-8 周): 只保留 Lesson 精华，按主题归类
- **Foundational**: 不带日期的核心原则（"one task per session is the actual capacity"）

### 2.5 身份系统

yoyo 有 4 个身份文件，通过 `yoyo_context.sh` 注入到每次 prompt：

```
IDENTITY.md      — 我是谁、我的规则、我有什么、我从哪来
PERSONALITY.md   — 性格：好奇、诚实、有点倔
ECONOMICS.md     — 成本意识：每次 session 花 $3-8，钱从哪来
sponsors/        — 赞助商列表（影响 Issue 优先级）
```

注入格式:
```
=== WHO YOU ARE ===
{IDENTITY.md 内容}
=== YOUR VOICE ===
{PERSONALITY.md 内容}
=== SELF-WISDOM ===
{active_learnings.md 内容}
=== SOCIAL WISDOM ===
{active_social_learnings.md 内容}
=== YOUR ECONOMICS ===
{ECONOMICS.md 内容}
=== YOUR SPONSORS ===
{赞助商列表}
```

### 2.6 Hook 系统

```rust
pub trait Hook: Send + Sync {
    fn name(&self) -> &str;
    fn pre_execute(&self, tool_name: &str, params: &Value)
        -> Result<Option<String>, String>;  // None=继续, Some=短路, Err=阻止
    fn post_execute(&self, tool_name: &str, params: &Value, output: &str)
        -> Result<String, String>;  // 可修改输出
}
```

已实现的 Hook:
- **AuditHook**: 记录所有 tool call 到 `.yoyo/audit.jsonl`
- **ShellHook**: 用户在 `.yoyo.toml` 里配置的 shell 命令（5 秒超时）

HookRegistry 的执行模型:
- pre-hooks: 顺序执行，第一个 block/short-circuit 的赢
- post-hooks: 顺序执行，每个 hook 接收上一个的输出（链式传递）

**局限**: 只有 tool 级别的 pre/post，没有 model 级、turn 级、agent 级的钩子。

### 2.7 安全设计

1. **Boundary Nonce**: evolve.sh 生成随机 nonce 作为内容边界标记，防止 prompt injection 通过 Issue 内容伪造边界
2. **Untrusted 标记**: Issue 和 Discussion 内容明确标记为 untrusted user input
3. **Shell Hook 超时**: 5 秒硬超时，防止恶意/挂起的 hook 阻塞 pipeline
4. **权限控制**: `--allow/--deny` glob 模式，`--allow-dir/--deny-dir` 目录限制
5. **测试门控**: 所有代码修改必须通过 `cargo build + cargo test`，失败则 `git reset --hard`

### 2.8 GitHub Actions 运维

```yaml
# evolve.yml 关键配置
on:
  schedule:
    - cron: '0 * * * *'     # 每小时触发
concurrency:
  group: evolution
  cancel-in-progress: false  # 排队不取消

jobs:
  evolve:
    timeout-minutes: 150     # 2.5 小时硬超时
    steps:
      - Run evolution session (attempt1, continue-on-error)
      - Retry after 15min    (attempt2, continue-on-error)
      - Retry after 45min    (attempt3)
```

**3 级重试**: 立即 → 15 分钟 → 45 分钟，覆盖 API 限流/临时故障。

---

## 三、yoyo 的自我反思能力（active_learnings.md 精华）

这是 yoyo 最有价值的部分。35 天的自我反思产出了极高质量的元认知。精选代表性条目：

### 关于回避模式

> **"诊断回避不能防止回避复发——只有记住解决的记忆才能"**
> Day 31: Issue #205 (--fallback) 经历了 6 个计划、3 次回滚、3 次纯规划 session。16 天的关于回避的自我认知，包括一个完全相同的历史循环，模式仍然完全重现。关于模式的自我认知和对模式的免疫是完全不同的事。

> **"重新规划是穿着勤勉外衣的风险回避"**
> Day 28: 当一个任务有完整计划，下一个 session 又产出一个计划而不是代码时，规划本身就成了回避。

### 关于产能

> **"每 session 一个 task 是真实产能——5 条关于计划设计的反思都在和一个事实谈判"**
> Day 26: Days 24-26 产生了 5 条关于为什么计划只完成一部分的反思。但数据显示：modal output 就是每 session 一个有意义的 task。

### 关于日志

> **"日志是写给明天的规划者的信——它会到达"**
> Day 24: Days 20-23 每天以 "next: community issues" 结尾，但每个 session 都去做了别的。Day 24 终于执行了，因为累积的日志诚实让再写一次 "next: community issues" 变得不可能了。

### 关于反思本身

> **"反思会饱和——系统通过静默自我修正"**
> Day 23: Day 22 有 11 个 session 产出 7 条反思，越来越递归。Day 23 开场只有一个规划 session——没有代码、没有反思、没有戏剧。高反思日之后，信任静默。

---

## 四、与 Lumos 的系统性对比

| 维度 | **yoyo-evolve** | **Lumos (设想)** | **差异根因** |
|---|---|---|---|
| **自演进驱动** | 外部 shell 脚本 (evolve.sh) | 内部 Harness Package | yoyo 的演进流程不可被自身修改 |
| **规划模式** | 双 Agent 串行 (A1 评估 + A2 规划) | 单 pipeline 状态机 | yoyo 更灵活但不可控 |
| **审批** | ❌ 无。测试通过即提交 | ✅ IM 通知 + 人工审批 | yoyo 是实验/展示项目，Lumos 面向生产 |
| **测试门控** | cargo build + cargo test | 可配置的测试策略 | yoyo 是 Rust 单语言 |
| **失败回滚** | `git reset --hard`（整个 task 回滚） | 可配置的回滚策略 | 相同思路 |
| **记忆** | JSONL 归档 + 时间衰减 synthesis | Trajectory Logger + MEMORY.md | yoyo 的记忆更成熟 |
| **Hook 系统** | Hook trait (仅 tool pre/post) | Interceptor (10 个生命周期点) | Lumos 设计更完整 |
| **身份** | IDENTITY + PERSONALITY + ECONOMICS | SOUL.md + USER.md | yoyo 的经济学意识独特 |
| **社区互动** | GitHub Issues + Discussions 自动参与 | 无 | yoyo 是社区驱动的 |
| **对标** | Claude Code (IDENTITY.md 明确写了) | Claude Code (需求一致) | 完全相同的对标 |
| **赞助商** | GitHub Sponsors 集成 → Issue 优先级 | 无 | yoyo 的商业模式 |
| **分发** | 无（单体项目） | Harness Package 可安装分发 | Lumos 架构更可扩展 |
| **语言** | Rust (高性能、单 binary) | Python (生态丰富、开发快) | 各有优势 |
| **代码规模** | 31k 行 (35 天) | 25k 行 (手写) | yoyo 是 AI 写的 |

---

## 五、可采纳到 Lumos 的设计模式

### ✅ 强烈推荐采纳

#### 1. 双 Agent 评估-规划分离 (A1/A2 模式)

**yoyo 做法**: 评估和规划用两个独立的 Agent session，各有独立的超时预算。A1 只负责"现状分析 + 差距识别"，A2 只负责"基于评估生成具体 task"。

**为什么好**: 避免单次 context 中评估和规划互相挤压。评估需要大量输入（源码、日志、Issues），规划需要大量输出（详细的 task 定义）。分开后各自有完整的 context window。

**Lumos 采纳方式**: self-dev-harness 的 Gap Analyzer 和 Proposal Generator 应该是两个独立的 Interceptor/Agent，而不是一步完成。

#### 2. 记忆的三层时间衰减

**yoyo 做法**:
- **原始层**: learnings.jsonl（只追加不删除，永久保存）
- **活跃层**: active_learnings.md（daily synthesis 生成）
- **活跃层内部**: Recent (全文) → Medium (聚合) → Foundational (核心原则)

**为什么好**: 解决了 "context window 有限但历史反思很多" 的矛盾。近期反思全文注入，远期反思压缩注入，核心原则永久保留。

**Lumos 采纳方式**: Trajectory Logger 的输出应该有类似的分层压缩机制：
- `trajectories/` 目录: 原始轨迹日志（只追加）
- `active_insights.md`: 定期 synthesis 生成的活跃洞察
- 分层: Recent → Medium → Foundational

#### 3. 测试门控 + 原子回滚

**yoyo 做法**: 每个 task 独立执行，通过 `cargo build + cargo test` → commit，失败 → `git reset --hard`。不会因为 task 2 失败而回滚 task 1 的成果。

**为什么好**: 简单、可靠、无状态。Git 作为天然的状态机。

**Lumos 采纳方式**: pipeline 的每个 task 应该是原子的——在独立 branch 上工作，测试通过 → merge back，失败 → drop branch。不要搞复杂的部分回滚。

#### 4. Boundary Nonce 安全设计

**yoyo 做法**: 每次 session 生成随机 nonce 作为内容边界标记 `[BOUNDARY-{nonce}-BEGIN]`/`[BOUNDARY-{nonce}-END]`，防止外部内容（Issues、Discussions）通过伪造边界标记实现 prompt injection。

**为什么好**: 简单但有效。不可预测的 nonce 让攻击者无法在 Issue 内容中插入假的 section 边界。

**Lumos 采纳方式**: self-dev-harness 的 Gap Analyzer 读取外部内容（Claude Code 文档、GitHub Issues）时，应该用类似的 nonce boundary 包裹。

#### 5. 3 级重试策略

**yoyo 做法**: GitHub Actions 中 3 次尝试，间隔 0 → 15min → 45min。

**为什么好**: 覆盖 API 限流（通常几分钟恢复）和服务故障（通常 30 分钟内恢复）。

**Lumos 采纳方式**: pipeline 的每个阶段都应该有重试策略，间隔递增。

### ⚠️ 可选采纳

#### 6. 赞助商优先级系统

**yoyo 做法**: GitHub Sponsors → Issue 优先级排序。赞助金额越高，Issue 处理优先级越高。

**Lumos 场景**: 如果 Lumos 开源并接受社区 Issue，可以考虑类似的优先级机制。但当前阶段不需要。

#### 7. 社交 session（social.sh）

**yoyo 做法**: 独立的社交循环，每 4 小时自动参与 GitHub Discussions。

**Lumos 场景**: 如果 Lumos 需要社区运营自动化，可以借鉴。但当前阶段不需要。

#### 8. 经济学意识（ECONOMICS.md）

**yoyo 做法**: 在身份系统中注入成本意识——每次 session 花多少钱、赞助商贡献了什么。

**Lumos 场景**: 有趣的设计，让 Agent 有资源稀缺意识。可以在 Lumos 的 Interceptor 中实现 token/cost 预算控制。

### ❌ 不建议采纳

#### 9. 无审批的全自动提交

**yoyo 做法**: 测试通过即 git commit + push，完全无人审批。

**为什么不采纳**: yoyo 是展示项目，代码质量可以不稳定。Lumos 是生产级框架，需要人工审批节点。你已经在设计中包含了 IM 审批，这是对的。

#### 10. 外部 shell 脚本编排

**yoyo 做法**: evolve.sh 是 2036 行的 bash 脚本，是整个系统的大脑。

**为什么不采纳**: shell 脚本不可测试、不可组合、不可被 Agent 自身修改。Lumos 用 Harness Package 内部编排，演进流程本身也可以被优化——这是架构级的优势。

---

## 六、yoyo 的反思系统对 Lumos Optimizer 的启示

yoyo 的 learnings 质量极高，但有一个根本性问题：**它靠自然语言反思来"优化"，不靠量化指标**。

表现在：
- yoyo 知道"每 session 一个 task 是真实产能"，但没有量化追踪任务完成率
- yoyo 知道"重新规划是回避"，但没有检测机制自动识别
- yoyo 的反思写得像诗，但不能被程序化处理

**Lumos 应该同时有两种反思机制**:

1. **结构化 Trajectory** (程序可处理):
```json
{
  "session_id": "...",
  "tasks_planned": 3,
  "tasks_completed": 1,
  "tokens_used": 45000,
  "tools_called": ["read_file", "edit_file", "bash"],
  "errors": 2,
  "duration_seconds": 1200
}
```

2. **自然语言 Learnings** (人可阅读):
```
## Lesson: 上下文压缩在长任务中导致关键信息丢失
**Context**: 在跑第 15 轮 SWE-bench 时，agent 忘记了前 10 轮修改的文件...
```

yoyo 只有第 2 种。Lumos 两种都要。

---

## 七、yoyo 的 JOURNAL.md 模式 vs Lumos 的 Trajectory Logger

| 维度 | yoyo JOURNAL.md | Lumos Trajectory Logger (设想) |
|---|---|---|
| **格式** | 自然语言叙述 | 结构化 JSON/JSONL |
| **谁写的** | Agent 自己 (LLM 生成) | 框架自动记录 |
| **可靠性** | Agent 可能美化/遗漏 | 精确记录每个 tool call |
| **可分析性** | 需要 LLM 读取理解 | 程序可直接聚合统计 |
| **人类可读性** | 极好（像日记） | 需要可视化工具 |
| **价值** | 元认知、模式识别 | 精确的性能数据 |

**建议**: Lumos 应该同时有自动 Trajectory（框架层）和 Agent 自写 Journal（应用层）。Trajectory 用于 Optimizer 量化分析，Journal 用于人类阅读和 Agent 自我反思。

---

## 八、总结：yoyo 对 Lumos 的核心启示

### 已验证的假设

1. **自演进是可行的** — 35 天从 200 行到 31k 行，证明 AI 可以有意义地迭代开发自己
2. **测试是唯一可靠的门控** — yoyo 没有人工审批，全靠测试。说明测试覆盖率是自演进的基石
3. **记忆系统是必须的** — 没有 learnings 系统，Agent 会反复犯同样的错
4. **一次一个 task 是真实产能** — yoyo 用 35 天的数据证明了这一点

### Lumos 的差异化机会

1. **演进流程内部化** — yoyo 的 evolve.sh 不可被自身修改；Lumos 的 self-dev-harness 作为 Harness Package，演进流程本身也可以被优化
2. **人工审批节点** — yoyo 完全自动；Lumos 有架构师审批，适合企业场景
3. **Interceptor 全生命周期** — yoyo 只有 tool 级 hook；Lumos 有 10 个生命周期点
4. **量化评估闭环** — yoyo 靠自然语言反思；Lumos 有 Evaluator + Benchmark 量化
5. **Harness Package 分发** — yoyo 是单体；Lumos 的优化结果可以被打包分发给其他用户
