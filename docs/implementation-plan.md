# Lumos 重构实施计划

> 基于 `refactor-design.md` v2.1-draft，逐 Phase、逐 Task 拆解到代码级别。
>
> 编写日期：2026-04-05

---

## 目录

- [Phase 1: 观测基础 (InterceptorEngine + TrajectoryLogger)](#phase-1-观测基础)
- [Phase 2: Harness Package + Workspace + PromptComposer](#phase-2-harness-package--workspace--promptcomposer)
- [Phase 3: Evaluation & Optimization](#phase-3-evaluation--optimization)
- [Phase 4: 生态成熟](#phase-4-生态成熟)
- [风险与缓解](#风险与缓解)

---

## Phase 1: 观测基础

> InterceptorEngine + TrajectoryLogger — 让 agent 的行为变得可观测。

### 最小可用版本（MVP）

**must-have（可以独立发布的最小集合）：**
- T1.1 InterceptorTypes — 所有数据类型定义
- T1.2 InterceptorEngine — 洋葱模型执行引擎
- T1.3 BaseInterceptor — 便利基类
- T1.5 agent_loop 改造 — 注入 interceptor_engine 可选参数

做到这一步就可以停下来发布。`interceptor_engine=None` 时行为与现在完全一致，传入 engine 后拦截器自动生效。这是整个重构的"地基"，后续所有功能都依赖它。

**nice-to-have（有了更好，但不阻塞发布）：**
- T1.4 ShellInterceptor（YAML 简写）
- T1.6 TrajectoryLogger
- T1.7 TrajectoryReplay
- T1.8 WriteRmLoopDetector 迁移

---

### T1.1: InterceptorTypes — 拦截器数据类型定义

**描述：** 定义 Interceptor 系统的所有数据类型：AgentContext、ModelRequest/Response、ToolRequest/Result、StopContext/Decision、AgentError/ErrorRecovery。

**输入：** 无依赖（最底层模块），仅导入 `core.types` 中的现有类型。

**产出文件清单：**
- `packages/server/interceptor/__init__.py`
- `packages/server/interceptor/types.py`

**实现要点：**
1. 所有数据类用 `@dataclass`，保持与现有 `core.types` 风格一致
2. `ModelRequest.with_overrides()` 用 `dataclasses.replace()` 而非 `asdict()` 再构造——`asdict()` 会递归序列化嵌套对象（如 `AgentTool`、`LLMConfig`），导致重构造失败
3. `AgentContext.tools` 引用 `core.tool.AgentTool`，用 `TYPE_CHECKING` 延迟导入避免循环依赖
4. 所有数据类保留 `metadata: dict[str, Any]` 字段，用于 interceptor 之间透传自定义数据
5. `ToolResult.content` 类型是 `list[ContentBlock]`，复用 `core.types.ContentBlock`

**单元测试：**
- `tests/test_interceptor_types.py`
  - `test_model_request_with_overrides()` — 验证 `with_overrides` 返回新对象，原对象不变
  - `test_agent_context_creation()` — 验证 AgentContext 可以正确构造，metadata 默认为空 dict
  - `test_stop_decision_defaults()` — 验证 StopDecision 的默认值（should_stop=True）
  - `test_error_recovery_defaults()` — 验证 ErrorRecovery 的默认值

**验收标准：**
```bash
pytest tests/test_interceptor_types.py -v
python -c "from packages.server.interceptor.types import AgentContext, ModelRequest; print('OK')"
```

---

### T1.2: InterceptorEngine — 洋葱模型执行引擎

**描述：** 实现拦截器的核心运行时——按 priority 排序拦截器，对每个生命周期点执行洋葱模型链。

**输入：** T1.1 InterceptorTypes

**产出文件清单：**
- `packages/server/interceptor/engine.py`

**实现要点：**
1. `_interceptors` 列表使用 lazy sort（`_sorted` flag），`register()` 时标记脏
2. `run_chain(event_name, initial_value, core_fn)` 构建递归洋葱链：`proceed()` 闭包捕获 `index + 1`，支持传值覆盖
3. `run_wrap(event_name, request, core_handler)` 用于 `wrap_model` / `wrap_tool`。**关键坑：闭包 late binding** — 必须用立即绑定的 `make_wrapper` 工厂函数
4. `_get_handlers(event_name)` 用 `hasattr + callable` 检查
5. 异常处理：log error 后 re-raise，不吃掉异常

**单元测试：**
- `tests/test_interceptor_engine.py`
  - `test_empty_engine_passthrough()` — 无拦截器时直接调用 core_fn
  - `test_single_interceptor_chain()` — 单个拦截器的 before/after 行为
  - `test_onion_order()` — 3 个拦截器（priority 10, 50, 90），验证执行顺序
  - `test_interceptor_block()` — 不调用 proceed()，core_fn 不执行
  - `test_interceptor_transform()` — 修改 request 后传递
  - `test_run_wrap_order()` — wrap 类型洋葱链顺序
  - `test_interceptor_exception_propagation()` — 异常传播
  - `test_register_unregister()` — 注册/注销
  - `test_priority_sort_lazy()` — lazy sort

**验收标准：**
```bash
pytest tests/test_interceptor_engine.py -v
```

---

### T1.3: BaseInterceptor — 便利基类与 Protocol

**描述：** 定义 `Interceptor` Protocol 和 `BaseInterceptor` 便利基类。

**输入：** T1.1 InterceptorTypes

**产出文件清单：**
- `packages/server/interceptor/protocol.py`
- `packages/server/interceptor/base.py`

**实现要点：**
1. `protocol.py` 定义 `Interceptor` Protocol（`@runtime_checkable`），只要求 `name: str` 和 `priority: int`
2. `base.py` 实现 10 个方法的默认透传：chain 类型 `return await proceed(value)`，wrap 类型 `return await handler(request)`
3. `name: str = ""`, `priority: int = 100` 作为类属性
4. 不使用 ABC，`BaseInterceptor` 可直接实例化

**单元测试：**
- `tests/test_interceptor_base.py`
  - `test_base_interceptor_passthrough()` — 所有方法透传
  - `test_subclass_override()` — 子类只覆盖 before_model
  - `test_protocol_check()` — isinstance 检查
  - `test_default_priority()` — 默认 100

**验收标准：**
```bash
pytest tests/test_interceptor_base.py -v
```

---

### T1.4: ShellInterceptor — YAML Shell 简写加载器

**描述：** 从 YAML 配置自动生成 shell 命令拦截器。

**输入：** T1.3 BaseInterceptor

**产出文件清单：**
- `packages/server/interceptor/shell.py`

**实现要点：**
1. 从 YAML dict 构造，`name` / `priority` 从配置读
2. Shell 协议：exit 0 = approve, exit 1 = block, exit 2 = transform
3. **设计文档坑**：`wait_for` 应包裹 `process.communicate()` 而非 `create_subprocess_shell`
4. `timeout` 强制上限 300 秒
5. `match` 字段用 `re.search()` 匹配工具名

**单元测试：**
- `tests/test_shell_interceptor.py`
  - `test_approve_passthrough()` / `test_block_tool()` / `test_transform_arguments()`
  - `test_match_filter()` / `test_timeout()`

**验收标准：**
```bash
pytest tests/test_shell_interceptor.py -v
```

---

### T1.5: agent_loop 改造 — 注入 InterceptorEngine

**描述：** 在 `agent_loop` 签名中新增 `interceptor_engine` 可选参数，在关键点插入拦截调用。

**输入：** T1.1 InterceptorTypes, T1.2 InterceptorEngine

**产出文件清单：**
- `packages/server/core/agent_loop.py`（修改）
- `packages/server/core/agent.py`（修改）

**实现要点：**
1. `agent_loop()` 新增 `interceptor_engine: Optional["InterceptorEngine"] = None`，默认 None 向后兼容
2. `_run_loop()` 同样透传
3. **9 个注入点**（仅 engine 不为 None 时）：
   - `before_agent` / `after_agent`：循环开始/结束时
   - `before_model` / `wrap_model` / `after_model`：包裹 stream_fn
   - `pre_tool_use` / `wrap_tool` / `post_tool_use`：包裹 tool.execute
   - `on_stop`：退出循环前
   - `on_error`：except 块
4. **stream_fn 桥接**：`before_model` 产生 `ModelRequest`，需要拆回 stream_fn 参数。构造一个 `_call_model(request: ModelRequest) -> ModelResponse` 闭包
5. `Agent` 类新增 `_interceptor_engine` 属性

**单元测试：**
- `tests/test_agent_loop_interceptor.py`
  - `test_loop_without_engine()` — None 时行为不变
  - `test_loop_with_empty_engine()` — 空 engine 行为与 None 一致
  - `test_before_model_intercept()` — request 被修改
  - `test_tool_intercept()` — 工具调用被拦截
  - `test_on_stop_override()` — 阻止停止
  - `test_on_error_recovery()` — 错误恢复

**验收标准：**
```bash
pytest tests/test_react_loop.py -v              # 现有测试通过
pytest tests/test_agent_loop_interceptor.py -v   # 新测试通过
```

---

### T1.6: TrajectoryLogger — 行为轨迹记录器

**描述：** 作为 Interceptor 实现的 JSONL 行为轨迹记录器。

**输入：** T1.3 BaseInterceptor, T1.5 agent_loop 改造

**产出文件清单：**
- `packages/server/trajectory/__init__.py`
- `packages/server/trajectory/logger.py`

**实现要点：**
1. 继承 `BaseInterceptor`，`priority = 1`（最外层）
2. 缓冲写入，超过 buffer_size 时 flush
3. **坑**：设计文档的 `self._file.open("a").write(...)` 泄漏句柄——改为 context manager + `asyncio.to_thread`
4. `after_agent` 必须 flush
5. 默认输出 `~/.lumos/trajectories/`，文件名 `{timestamp}_{session_id}.jsonl`
6. 超大 arguments 截断（1000 chars）

**单元测试：**
- `tests/test_trajectory_logger.py`
  - `test_emit_agent_start()` / `test_emit_model_events()` / `test_emit_tool_events()`
  - `test_buffer_flush()` / `test_final_flush()`
  - `test_jsonl_format()` / `test_large_argument_truncation()`

**验收标准：**
```bash
pytest tests/test_trajectory_logger.py -v
```

---

### T1.7: TrajectoryReplay — 行为轨迹重放

**描述：** 从 JSONL 文件读取事件序列，提供统计分析。

**输入：** T1.6 的 JSONL 格式

**产出文件清单：**
- `packages/server/trajectory/replay.py`

**实现要点：**
1. `events()` generator 逐行读取
2. `summary()` 统计 turns / tool_calls / tokens / duration
3. `tool_sequence()` 提取工具序列
4. 空文件 / 坏行健壮处理

**单元测试：**
- `tests/test_trajectory_replay.py`
  - `test_events_iterator()` / `test_summary_stats()` / `test_tool_sequence()`
  - `test_empty_file()` / `test_corrupted_line()` / `test_filter_events()`

**验收标准：**
```bash
pytest tests/test_trajectory_replay.py -v
```

---

### T1.8: WriteRmLoopDetector — 迁移为 Interceptor

**描述：** 将 `LumosAgent._detect_write_rm_loop()` 迁移为可插拔 interceptor。

**输入：** T1.3 BaseInterceptor

**产出文件清单：**
- `packages/server/interceptor/builtins/__init__.py`
- `packages/server/interceptor/builtins/loop_detector.py`
- `packages/server/agents/lumos_agent.py`（修改）

**实现要点：**
1. `WriteRmLoopDetector`：`name = "write-rm-loop-detector"`, `priority = 80`
2. `post_tool_use` 记录历史，检测 write→rm 循环
3. 有 engine 时跳过 LumosAgent 的硬编码逻辑
4. `threshold` 参数化

**单元测试：**
- `tests/test_loop_detector.py`
  - `test_no_loop_no_warning()` / `test_write_rm_loop_detected()`
  - `test_threshold_configurable()` / `test_warning_only_once()` / `test_history_sliding_window()`

**验收标准：**
```bash
pytest tests/test_loop_detector.py -v
```

### Phase 1 E2E 测试

#### E2E-P1-01: Interceptor 洋葱模型透传
**前置条件**: InterceptorEngine + BaseInterceptor 已实现
**步骤**:
1. 注册 3 个 interceptor（priority 10, 50, 90），每个在 before_model 中记录自己的 name 到共享列表
2. 触发 before_model 事件
3. 验证执行顺序是 10 → 50 → 90 → core
**期望结果**: 共享列表为 `["p10", "p50", "p90"]`，core_fn 被调用一次
**自动化**: `pytest tests/e2e/test_e2e_phase1.py::test_onion_passthrough`

#### E2E-P1-02: Interceptor 阻断
**前置条件**: 同上
**步骤**:
1. 注册 2 个 interceptor，priority=10 的在 pre_tool_use 中返回 ToolResult(is_error=True) 不调用 proceed
2. 触发 pre_tool_use
**期望结果**: priority=50 的 interceptor 和 core_fn 都不被调用，返回 error ToolResult
**自动化**: `pytest tests/e2e/test_e2e_phase1.py::test_interceptor_block`

#### E2E-P1-03: Interceptor 变换
**前置条件**: 同上
**步骤**:
1. 注册 interceptor 在 before_model 中修改 request.model 为 "modified-model"
2. 触发 before_model
**期望结果**: core_fn 收到的 request.model == "modified-model"
**自动化**: `pytest tests/e2e/test_e2e_phase1.py::test_interceptor_transform`

#### E2E-P1-04: 向后兼容 — interceptor_engine=None
**前置条件**: agent_loop 改造完成
**步骤**:
1. 用现有方式调用 agent_loop（不传 interceptor_engine）
2. 执行一次完整的 tool call 循环
**期望结果**: 行为与改造前完全一致，无报错
**自动化**: `pytest tests/e2e/test_e2e_phase1.py::test_backward_compat_no_engine`

#### E2E-P1-05: TrajectoryLogger 全链路
**前置条件**: TrajectoryLogger + agent_loop 改造完成
**步骤**:
1. 创建 InterceptorEngine，注册 TrajectoryLogger(output_dir=tmp_dir)
2. 用 mock stream_fn 和 mock tool 跑一次 agent_loop
3. 检查 tmp_dir 下生成的 JSONL 文件
**期望结果**: JSONL 包含 agent_start, model_request, model_response, tool_start, tool_end, agent_end 事件，顺序正确
**自动化**: `pytest tests/e2e/test_e2e_phase1.py::test_trajectory_logger_full_chain`

#### E2E-P1-06: TrajectoryReplay 统计
**前置条件**: E2E-P1-05 生成的 JSONL 文件
**步骤**:
1. 用 TrajectoryReplay 加载 JSONL
2. 调用 summary() 和 tool_sequence()
**期望结果**: summary 的 turns/tool_calls/duration_s 与实际一致，tool_sequence 返回正确的工具名列表
**自动化**: `pytest tests/e2e/test_e2e_phase1.py::test_trajectory_replay_summary`

#### E2E-P1-07: ShellInterceptor YAML 加载
**前置条件**: ShellInterceptor 已实现
**步骤**:
1. 创建 YAML 文件定义 pre_tool_use 事件，command 为 `echo "blocked" >&2 && exit 1`
2. 加载为 ShellInterceptor，注册到 engine
3. 触发 pre_tool_use
**期望结果**: 工具被阻止，返回 is_error=True 的 ToolResult，内容包含 "blocked"
**自动化**: `pytest tests/e2e/test_e2e_phase1.py::test_shell_interceptor_block`

---


## Phase 2: Harness Package + Workspace + PromptComposer

> 让 harness 配置可以被打包、安装、分发；让 system prompt 从硬编码变为动态组装。

### 最小可用版本（MVP）

**must-have：**
- T2.1 PromptComposer + PromptSection — system prompt 动态组装
- T2.2 WorkspaceLoader — 加载 AGENT.md / IDENTITY.md / USER.md / LUMOS.md
- T2.3 `lumos init` + `lumos setup` — 首次引导
- T2.5 HarnessLoader — 从 HARNESS.yaml 加载资源

做到这一步可以发布：用户可以用 LUMOS.md 定制项目指令，PromptComposer 替代硬编码 prompt。

**nice-to-have：**
- T2.4 ContextCompressor interceptor
- T2.6 HarnessManager + CLI（install/use/current/uninstall）
- T2.7 Harness Compose
- T2.8 MemorySynthesizer（learnings.jsonl → active_insights.md）

---

### T2.1: PromptComposer + PromptSection

**描述：** 实现 system prompt 的 9 层动态组装器，替代 `LumosAgent.DEFAULT_SYSTEM_PROMPT`。

**输入：** 无新依赖（使用现有 SkillManager、ModeManager）

**产出文件清单：**
- `packages/server/capability/__init__.py`
- `packages/server/capability/prompt_composer.py`
- `packages/server/agents/lumos_agent.py`（修改：`_build_system_prompt` 委托给 PromptComposer）

**实现要点：**
1. `PromptSection` dataclass：name, content, priority(1-9), compressible, source, token_estimate
2. `PromptComposer.compose()` 按 L1-L9 顺序组装，返回完整 prompt 字符串
3. token 估算用简单的 `len(content) // 4` 近似，不引入 tiktoken 依赖
4. 压缩策略 v1：超预算时从 L8→L5 依次截断到 max_chars，L1-L3 永不压缩
5. 保留 `DEFAULT_SYSTEM_PROMPT` 作为 fallback——PromptComposer 找不到任何 workspace 文件时退回硬编码

**单元测试：**
- `tests/test_prompt_composer.py`
  - `test_compose_all_layers()` — 9 层全有时的组装结果
  - `test_compose_missing_files()` — 部分文件缺失时 graceful fallback
  - `test_compression_order()` — 超预算时 L8 先被压缩，L1 不动
  - `test_fallback_to_default()` — 无 workspace 文件时退回 DEFAULT_SYSTEM_PROMPT
  - `test_section_to_prompt_format()` — 验证 `=== NAME ===` 格式

**验收标准：**
```bash
pytest tests/test_prompt_composer.py -v
# 现有测试全部通过（向后兼容）
pytest tests/ -v --tb=short
```

---

### T2.2: WorkspaceLoader

**描述：** 加载全局 workspace（`~/.lumos/`）和项目级 workspace（`<project>/.lumos/` + `LUMOS.md`）的文件。

**输入：** 无

**产出文件清单：**
- `packages/server/capability/workspace_loader.py`

**实现要点：**
1. `WorkspaceLoader(global_path, project_root)` — 两个路径
2. `load_file(name, layer)` — 按优先级搜索：项目级 > 全局级 > 内置默认
3. LUMOS.md 级联搜索：从 cwd 向上到 project_root，所有找到的合并
4. 兼容 CLAUDE.md：搜索 `["LUMOS.md", "CLAUDE.md"]`，LUMOS.md 优先
5. 文件不存在时返回 None，不报错

**单元测试：**
- `tests/test_workspace_loader.py`
  - `test_project_overrides_global()` — 项目级 IDENTITY.md 覆盖全局
  - `test_lumos_md_cascade()` — 子目录 + 项目根的 LUMOS.md 合并
  - `test_claude_md_fallback()` — 没有 LUMOS.md 时读 CLAUDE.md
  - `test_missing_files_graceful()` — 文件不存在返回 None

**验收标准：**
```bash
pytest tests/test_workspace_loader.py -v
```

---

### T2.3: lumos init + lumos setup

**描述：** 首次运行引导命令。`lumos init` 生成项目级 LUMOS.md，`lumos setup` 生成全局 workspace。

**输入：** T2.2 WorkspaceLoader

**产出文件清单：**
- `packages/server/cli/init_cmd.py`
- `packages/server/cli/setup_cmd.py`
- `packages/server/capability/project_scanner.py`

**实现要点：**
1. `ProjectScanner.scan()` 检测语言（Cargo.toml/pyproject.toml/package.json）、构建命令、测试命令
2. `lumos init` 生成 LUMOS.md 模板，包含自动检测的信息
3. `lumos setup` 交互式引导：Agent 名字、用户名字、时区 → 生成 ~/.lumos/{IDENTITY.md, USER.md, AGENT.md}
4. 检测已有 CLAUDE.md，提示是否迁移
5. 幂等：已存在的文件不覆盖，提示用户

**单元测试：**
- `tests/test_project_scanner.py`
  - `test_detect_python()` / `test_detect_rust()` / `test_detect_node()`
  - `test_detect_unknown()`

**验收标准：**
```bash
cd /tmp/test-project && lumos init  # 生成 LUMOS.md
ls ~/.lumos/IDENTITY.md             # lumos setup 后存在
```

---

### T2.4: ContextCompressor Interceptor

**描述：** 在 `before_model` 拦截点实现上下文窗口管理——当 messages 总 token 超过阈值时自动压缩。

**输入：** T1.3 BaseInterceptor

**产出文件清单：**
- `packages/server/interceptor/builtins/context_compressor.py`

**实现要点：**
1. `SlidingWindowCondenser`：`name = "context-compressor"`, `priority = 30`
2. `before_model` 中估算 messages 总 token，超过 threshold 时执行压缩
3. 策略 v1：`keep_recent` — 保留最近 N 条 message，丢弃最早的
4. 策略 v2（后续）：`summarize_old` — 用小模型摘要旧消息
5. 不压缩 system prompt（那是 PromptComposer 的事）

**单元测试：**
- `tests/test_context_compressor.py`
  - `test_no_compression_under_threshold()`
  - `test_keep_recent_strategy()`
  - `test_system_messages_preserved()`

**验收标准：**
```bash
pytest tests/test_context_compressor.py -v
```

---

### T2.5: HarnessLoader

**描述：** 从 HARNESS.yaml 加载 interceptors / tools / skills / prompts / config。

**输入：** T1.2 InterceptorEngine, T1.3 BaseInterceptor

**产出文件清单：**
- `packages/server/harness/__init__.py`
- `packages/server/harness/loader.py`

**实现要点：**
1. 解析 HARNESS.yaml 的 `provides` 字段
2. Python interceptor：动态 import → 实例化（传入 config）
3. YAML interceptor：加载为 ShellInterceptor
4. tools：扫描 AgentTool 实例 + `create_*_tool()` 工厂函数
5. skills：返回目录路径列表给 SkillManager
6. prompts：读取 system_append 文件内容
7. config：加载 YAML 返回 dict

**单元测试：**
- `tests/test_harness_loader.py`
  - `test_load_python_interceptor()` — 动态 import + 实例化
  - `test_load_yaml_interceptor()` — YAML → ShellInterceptor
  - `test_load_tools()` — 扫描 AgentTool
  - `test_load_prompts()` — 读取 system_append
  - `test_missing_harness_yaml()` — FileNotFoundError
  - `test_empty_provides()` — 空 provides 不报错

**验收标准：**
```bash
pytest tests/test_harness_loader.py -v
```

---

### T2.6: HarnessManager + CLI

**描述：** 单活跃 Harness 管理——install / use / current / list / uninstall。

**输入：** T2.5 HarnessLoader

**产出文件清单：**
- `packages/server/harness/manager.py`
- `packages/server/cli/harness_cmd.py`

**实现要点：**
1. `install(source)` — 复制目录到 `~/.lumos/packages/<name>/`
2. `use(name)` — 写入 `~/.lumos/config/lumos.yaml` 的 `active_harness` 字段
3. `current()` — 读取 active_harness，项目级优先
4. `uninstall(name)` — 删除目录，如果是 active 则重置为 default
5. 单活跃模型：同一时刻只有一个 harness 生效

**单元测试：**
- `tests/test_harness_manager.py`
  - `test_install_and_list()` / `test_use_and_current()`
  - `test_uninstall_active_resets_to_default()`
  - `test_project_level_overrides_global()`

**验收标准：**
```bash
lumos harness install ./test-harness
lumos harness use test-harness
lumos harness current  # → test-harness
lumos harness uninstall test-harness
```

---

### T2.7: Harness Compose

**描述：** 显式组合两个 harness 为一个新的独立 harness。

**输入：** T2.5 HarnessLoader

**产出文件清单：**
- `packages/server/harness/compose.py`

**实现要点：**
1. `compose(base, mixin, output_name)` — 以 base 为基础，mixin 的资源追加进来
2. interceptors/tools/skills/prompts：追加
3. config：mixin 覆盖 base 的同名字段（深度合并）
4. 同名 interceptor/tool：交互式询问（CLI）或 mixin 优先（API）
5. 产出独立的 harness 目录，可以直接 `lumos harness install`

**单元测试：**
- `tests/test_harness_compose.py`
  - `test_compose_interceptors_merged()`
  - `test_compose_config_deep_merge()`
  - `test_compose_name_conflict_mixin_wins()`

**验收标准：**
```bash
lumos harness compose --base A --mixin B --name C
ls ~/.lumos/packages/C/HARNESS.yaml  # 存在
```

---

### T2.8: MemorySynthesizer

**描述：** 从 learnings.jsonl 生成 active_insights.md，三层时间衰减。

**输入：** 无新依赖

**产出文件清单：**
- `packages/server/memory/__init__.py`
- `packages/server/memory/synthesizer.py`

**实现要点：**
1. 读取 learnings.jsonl，按时间分三层：Recent(< 2 周) / Medium(2-8 周) / Foundational(> 8 周)
2. Recent：保留完整 lesson + context
3. Medium：按主题聚合（v1 用简单的关键词匹配，不引入 LLM）
4. Foundational：提取核心原则（v1 取 Medium 中出现 2+ 次的主题）
5. 输出 Markdown 格式的 active_insights.md

**单元测试：**
- `tests/test_memory_synthesizer.py`
  - `test_recent_entries_full_text()`
  - `test_medium_entries_grouped()`
  - `test_empty_jsonl_produces_skeleton()`

**验收标准：**
```bash
pytest tests/test_memory_synthesizer.py -v
```

---

### Phase 2 E2E 测试

#### E2E-P2-01: PromptComposer 替代硬编码 prompt
**前置条件**: PromptComposer + WorkspaceLoader 已实现
**步骤**:
1. 创建 tmp 目录作为 global workspace，写入 IDENTITY.md ("你是 TestBot") 和 AGENT.md
2. 创建 tmp 项目目录，写入 LUMOS.md ("这是一个 Python 项目")
3. 用 PromptComposer 组装 prompt
**期望结果**: prompt 包含 "TestBot"、"Python 项目"，格式为 `=== IDENTITY ===` section
**自动化**: `pytest tests/e2e/test_e2e_phase2.py::test_prompt_composer_replaces_hardcoded`

#### E2E-P2-02: LUMOS.md 级联加载
**前置条件**: WorkspaceLoader 已实现
**步骤**:
1. 创建 project/LUMOS.md ("项目根指令") 和 project/src/LUMOS.md ("子目录指令")
2. cwd 设为 project/src/，加载 LUMOS.md
**期望结果**: 两个文件内容都被加载，项目根在前、子目录在后
**自动化**: `pytest tests/e2e/test_e2e_phase2.py::test_lumos_md_cascade`

#### E2E-P2-03: CLAUDE.md 兼容
**前置条件**: WorkspaceLoader 已实现
**步骤**:
1. 创建项目目录，只有 CLAUDE.md 没有 LUMOS.md
2. 加载项目指令
**期望结果**: CLAUDE.md 内容被加载
**自动化**: `pytest tests/e2e/test_e2e_phase2.py::test_claude_md_compat`

#### E2E-P2-04: Harness 安装 → 激活 → agent 行为变化
**前置条件**: HarnessManager + HarnessLoader + PromptComposer 已实现
**步骤**:
1. 创建 test-harness/ 包含 prompts/extra.md ("Always respond in JSON")
2. `lumos harness install ./test-harness`
3. `lumos harness use test-harness`
4. 用 PromptComposer 组装 prompt
**期望结果**: prompt 末尾包含 "Always respond in JSON"
**自动化**: `pytest tests/e2e/test_e2e_phase2.py::test_harness_install_use_prompt`

#### E2E-P2-05: Harness 单活跃模型
**前置条件**: HarnessManager 已实现
**步骤**:
1. 安装 harness-A 和 harness-B
2. `lumos harness use harness-A`
3. `lumos harness use harness-B`
4. `lumos harness current`
**期望结果**: current 返回 harness-B（不是两个同时激活）
**自动化**: `pytest tests/e2e/test_e2e_phase2.py::test_single_active_harness`

#### E2E-P2-06: lumos init 自动检测
**前置条件**: ProjectScanner 已实现
**步骤**:
1. 创建 tmp 目录，放入 pyproject.toml
2. 运行 lumos init
**期望结果**: 生成 LUMOS.md，包含 "Python" 和 `pytest` 相关内容
**自动化**: `pytest tests/e2e/test_e2e_phase2.py::test_lumos_init_python_project`

---


## Phase 3: Evaluation & Optimization

> 完成自优化闭环——量化评估 harness 效果，自动调参。

### 最小可用版本（MVP）

**must-have：**
- T3.1 Evaluator 基类 + EvalResult
- T3.2 EfficiencyEvaluator（内置）
- T3.3 OptimizationWorkspace 初始化
- T3.4 BenchmarkRunner（单线程版）

做到这一步可以发布：用户可以手动跑 benchmark → 看分数 → 手动调 harness → 再跑。闭环靠人驱动。

**nice-to-have：**
- T3.5 自动 hill-climbing 优化循环
- T3.6 scores.tsv + git-backed keep-or-revert
- T3.7 `lumos optimize export`
- T3.8 SWE-bench-lite 对接

---

### T3.1: Evaluator 基类

**描述：** 定义不可变评估锚点的抽象基类。

**输入：** T1.7 TrajectoryReplay

**产出文件清单：**
- `packages/server/evaluator/__init__.py`
- `packages/server/evaluator/base.py`

**实现要点：**
1. `Evaluator` ABC：`name` property + `evaluate(trajectory, task) -> EvalResult`
2. `EvalResult` dataclass：score(0-1), passed(bool), details(dict), reason(str)
3. Evaluator 文件一旦建立只追加不修改（immutable anchor 约定，文档级约束）
4. evaluate 接收 TrajectoryReplay 而非原始 JSONL 路径

**单元测试：**
- `tests/test_evaluator_base.py`
  - `test_eval_result_creation()`
  - `test_abstract_evaluator_cannot_instantiate()`

**验收标准：**
```bash
pytest tests/test_evaluator_base.py -v
```

---

### T3.2: EfficiencyEvaluator

**描述：** 内置效率评估器——衡量 agent 用了多少步骤和 token 完成任务。

**输入：** T3.1 Evaluator 基类

**产出文件清单：**
- `packages/server/evaluator/builtins/__init__.py`
- `packages/server/evaluator/builtins/efficiency.py`

**实现要点：**
1. 分数公式：`1.0 / (1.0 + tool_ratio + token_ratio)`
2. `max_expected_tool_calls` 和 `max_expected_tokens` 可配置
3. 从 TrajectoryReplay.summary() 获取数据

**单元测试：**
- `tests/test_efficiency_evaluator.py`
  - `test_perfect_efficiency()` — 0 tool calls → score 接近 1.0
  - `test_high_cost_low_score()` — 超过 max 的 2 倍 → score < 0.3
  - `test_configurable_thresholds()`

**验收标准：**
```bash
pytest tests/test_efficiency_evaluator.py -v
```

---

### T3.3: OptimizationWorkspace

**描述：** 管理优化任务的目录结构和状态。

**输入：** T2.5 HarnessLoader

**产出文件清单：**
- `packages/server/optimization/__init__.py`
- `packages/server/optimization/workspace.py`
- `packages/server/cli/optimize_cmd.py`

**实现要点：**
1. `lumos optimize init --name X --benchmark Y --harness Z` 创建目录结构
2. 每个优化任务是独立目录：`.lumos/optimization/<name>/`
3. 复制目标 harness 到 `workspace/harness/` 作为 baseline
4. 初始化 git repo（用于 keep-or-revert）
5. 生成 WORKSPACE.yaml
6. `lumos optimize list` 列出所有优化任务

**单元测试：**
- `tests/test_optimization_workspace.py`
  - `test_init_creates_structure()`
  - `test_init_copies_harness()`
  - `test_list_workspaces()`
  - `test_init_idempotent()` — 重复 init 不覆盖

**验收标准：**
```bash
lumos optimize init --name test-opt --benchmark dummy --harness ./test-harness
ls .lumos/optimization/test-opt/WORKSPACE.yaml  # 存在
```

---

### T3.4: BenchmarkRunner

**描述：** 批量运行 benchmark 任务集，收集 trajectory。

**输入：** T3.3 OptimizationWorkspace, T1.6 TrajectoryLogger

**产出文件清单：**
- `packages/server/optimization/runner.py`

**实现要点：**
1. 读取 tasks.jsonl，逐个任务创建 agent + 注入 harness + 运行
2. 每个任务的 trajectory 保存到 `trajectories/round_N/task_XXX.jsonl`
3. v1 单线程串行，v2 再加并行
4. 超时控制：每个任务有 max_seconds
5. 任务失败不中断整个 benchmark

**单元测试：**
- `tests/test_benchmark_runner.py`
  - `test_run_single_task()` — mock agent，验证 trajectory 生成
  - `test_task_timeout()` — 超时任务被跳过
  - `test_task_failure_continues()` — 单个失败不中断

**验收标准：**
```bash
pytest tests/test_benchmark_runner.py -v
```

---

### T3.5: 自动优化循环

**描述：** `lumos optimize run --rounds N` 自动执行 N 轮优化。

**输入：** T3.4 BenchmarkRunner, T3.1 Evaluator

**产出文件清单：**
- `packages/server/optimization/optimizer.py`

**实现要点：**
1. 每轮：跑 benchmark → evaluate → 记录 score → 调参 → 下一轮
2. v1 调参策略：hill-climbing（随机微调一个参数，score 提升则保留）
3. 可调参数：config/overrides.yaml 中的数值型字段
4. scores.tsv 追加每轮结果
5. git commit 每轮变更，score 下降则 git revert

**单元测试：**
- `tests/test_optimizer.py`
  - `test_hill_climb_keeps_improvement()`
  - `test_hill_climb_reverts_regression()`
  - `test_scores_tsv_appended()`

**验收标准：**
```bash
lumos optimize run --workspace test-opt --rounds 3
cat .lumos/optimization/test-opt/scores.tsv  # 3 行
```

---

### T3.6 - T3.8: 略（scores.tsv git-backed、export、SWE-bench 对接）

这些是 T3.5 的自然延伸，实现要点已在 refactor-design.md §7 中详述。

---

### Phase 3 E2E 测试

#### E2E-P3-01: 评估器独立于 agent
**前置条件**: Evaluator + TrajectoryReplay 已实现
**步骤**:
1. 手动构造一个 JSONL trajectory 文件（不需要真正跑 agent）
2. 用 EfficiencyEvaluator 评估
**期望结果**: 返回 EvalResult，score 在 0-1 之间
**自动化**: `pytest tests/e2e/test_e2e_phase3.py::test_evaluator_standalone`

#### E2E-P3-02: 优化 workspace 完整生命周期
**前置条件**: OptimizationWorkspace + BenchmarkRunner + Evaluator 已实现
**步骤**:
1. `lumos optimize init --name e2e-test --benchmark dummy --harness ./test-harness`
2. `lumos optimize run --workspace e2e-test --rounds 2`（用 mock agent）
3. `lumos optimize scores --workspace e2e-test`
**期望结果**: scores.tsv 有 2 行，每行有 round/score/delta/date
**自动化**: `pytest tests/e2e/test_e2e_phase3.py::test_optimize_lifecycle`

#### E2E-P3-03: keep-or-revert 机制
**前置条件**: T3.5 自动优化循环已实现
**步骤**:
1. 构造 mock evaluator：round 1 返回 0.5，round 2 返回 0.3（退步）
2. 运行 2 轮优化
3. 检查 git log
**期望结果**: round 2 的 commit 被 revert，harness 回到 round 1 的状态
**自动化**: `pytest tests/e2e/test_e2e_phase3.py::test_keep_or_revert`

---


## Phase 4: 生态成熟（持续）

> 社区可共建的 harness 生态。

### 最小可用版本（MVP）

**must-have：**
- T4.1 Harness Registry（基于 git 的简单 registry）
- T4.2 `lumos harness publish` 命令

**nice-to-have：**
- T4.3 更多内置 interceptors（RepoMapInjector, AutoLint, CostBudget）
- T4.4 更多 evaluators（TaskCompletion, CodeQuality）
- T4.5 更多 benchmark 对接（τ-bench, GAIA, Aider Polyglot）
- T4.6 Web dashboard（优化历史可视化）

Phase 4 是持续迭代，不设硬性截止日期。

---

### T4.1: Harness Registry

**描述：** 基于 git 的简单 registry，用户可以发布和搜索 harness。

**产出文件清单：**
- `packages/server/harness/registry.py`
- `packages/server/cli/harness_cmd.py`（扩展 publish/search）

**实现要点：**
1. Registry 是一个 git repo，每个 harness 是一个子目录
2. `lumos harness publish` — 验证 HARNESS.yaml → 推送到 registry repo
3. `lumos harness search <keyword>` — 搜索 registry
4. provenance 验证：检查 HARNESS.yaml 中的 benchmark score 声明

---

### T4.2 - T4.6: 略

这些是社区驱动的持续迭代，具体实现随需求演进。

---


## 风险与缓解

### R1: agent_loop 改造破坏现有行为
**风险等级**: 高
**描述**: agent_loop 是核心循环，任何改动都可能引入微妙的行为变化（消息顺序、tool call 时序、错误处理路径）
**缓解**:
- `interceptor_engine=None` 时走完全相同的代码路径（if/else 分支，不是抽象层）
- 改造前先补充 agent_loop 的集成测试（录制当前行为作为 baseline）
- 改造后跑完整的现有测试套件 + E2E-P1-04 向后兼容测试
**检测**: 现有 `tests/test_react_loop.py` 全部通过

### R2: 动态 import interceptor 的安全风险
**风险等级**: 中
**描述**: HarnessLoader 用 `importlib` 动态加载 Python 文件，恶意 harness 可以执行任意代码
**缓解**:
- v1 只支持本地路径安装（用户自己下载的，信任用户判断）
- v2 registry 加入签名验证
- 文档明确警告：只安装你信任的 harness
**检测**: 代码审查

### R3: PromptComposer 组装的 prompt 太长
**风险等级**: 中
**描述**: 9 层全部加载后可能超过模型的 context window，特别是 LUMOS.md 很长 + 多个 harness prompts + 活跃记忆
**缓解**:
- 压缩策略：L8→L5 依次截断
- token 预算硬上限（默认 system prompt 不超过 context window 的 30%）
- `lumos harness inspect` 显示当前 prompt 的 token 估算
**检测**: E2E-P2-01 中验证压缩行为

### R4: ShellInterceptor 超时/挂起
**风险等级**: 中
**描述**: 用户配置的 shell 命令可能挂起，阻塞整个 agent 循环
**缓解**:
- 硬超时（默认 5 秒，可配置）
- 超时后 kill 进程，记录警告，继续执行（不阻断 agent）
- 参考 yoyo-evolve 的 ShellHook 5 秒超时设计
**检测**: E2E-P1-07 中测试超时行为

### R5: learnings.jsonl 无限增长
**风险等级**: 低
**描述**: learnings.jsonl 只追加不删除，长期使用后文件可能很大
**缓解**:
- MemorySynthesizer 生成 active_insights.md 后，只有 active 文件被注入 prompt
- learnings.jsonl 本身不注入 prompt，只是归档
- 未来可加 archive 机制（> 6 个月的条目压缩为 .jsonl.gz）
**检测**: 监控文件大小

### R6: 单活跃 Harness 模型的局限性
**风险等级**: 低
**描述**: 用户可能确实需要同时使用两个 harness 的能力（如 safety + coding-style）
**缓解**:
- `lumos harness compose` 显式组合为一个新 harness
- 文档引导用户用 compose 而非要求运行时 stack
- 如果社区反馈强烈，Phase 4 可以考虑加回轻量级 stack
**检测**: 用户反馈

### R7: Optimization 的 git-backed revert 与用户手动修改冲突
**风险等级**: 低
**描述**: 用户在优化过程中手动修改了 harness 文件，git revert 可能产生冲突
**缓解**:
- 优化运行期间锁定 workspace（写入 .lock 文件）
- revert 失败时保留当前状态，记录警告，让用户手动解决
**检测**: T3.5 单元测试覆盖 revert 失败场景

---

## 附录：Task 依赖图

```
T1.1 InterceptorTypes
 ├── T1.2 InterceptorEngine
 │    ├── T1.5 agent_loop 改造
 │    │    ├── T1.6 TrajectoryLogger
 │    │    │    └── T1.7 TrajectoryReplay
 │    │    │         └── T3.1 Evaluator
 │    │    │              └── T3.2 EfficiencyEvaluator
 │    │    │              └── T3.4 BenchmarkRunner
 │    │    │                   └── T3.5 Optimizer
 │    │    └── E2E-P1-04 向后兼容
 │    └── T2.5 HarnessLoader
 │         ├── T2.6 HarnessManager
 │         │    └── T2.7 Harness Compose
 │         └── T3.3 OptimizationWorkspace
 ├── T1.3 BaseInterceptor
 │    ├── T1.4 ShellInterceptor
 │    ├── T1.8 WriteRmLoopDetector
 │    └── T2.4 ContextCompressor
 └── (独立)
      ├── T2.1 PromptComposer
      │    └── T2.2 WorkspaceLoader
      │         └── T2.3 lumos init/setup
      └── T2.8 MemorySynthesizer
```

**关键路径**: T1.1 → T1.2 → T1.5 → T1.6 → T1.7 → T3.1 → T3.4 → T3.5

**可并行的独立线**:
- 线 A: T1.1 → T1.3 → T1.8（interceptor 内置实现）
- 线 B: T2.1 → T2.2 → T2.3（workspace + prompt，不依赖 interceptor）
- 线 C: T2.8（记忆系统，完全独立）
