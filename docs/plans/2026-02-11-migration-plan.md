# Lumos 迁移实施计划

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 将 openjiuwen-code 项目重构为独立的 Lumos 项目，完全去除 openJiuwen SDK 依赖，自建 ReAct Agent 核心。

**Architecture:** Lumos 采用自建 ReAct Agent 循环，直接调用 LLM API（Anthropic/OpenAI），不依赖任何第三方 Agent 框架。工具系统使用自定义 BaseTool 抽象，保持与原项目相同的工具能力。

**Tech Stack:** Python 3.10+, Anthropic SDK, OpenAI SDK, Rich (TUI), FastAPI (Web), prompt-toolkit

---

## 迁移总览

### 模块分类

| 分类 | 文件数 | 策略 | 说明 |
|------|--------|------|------|
| **A: 直接复用** | 53 | 原样复制 | 无 SDK 依赖，零修改 |
| **B: 换 import** | 14 | 复制 + 改 import | 工具文件，逻辑不变 |
| **C: 重写** | 1 | 全新实现 | openjiuwen_agent.py → lumos_agent.py |
| **D: 新建** | ~5 | 从零写 | 自建 core 层替代 SDK |

### 依赖变化

```
# 移除
- openjiuwen>=0.1.0  (SDK)
- agent-core/         (子模块)

# 保留
- anthropic, openai   (直接调用 LLM API)
- rich, prompt-toolkit (CLI/TUI)
- fastapi, websockets  (Web UI)
- aiohttp, aiofiles   (异步)
- pyyaml              (配置)

# 新增
- (无额外依赖，自建 core 层纯 Python 实现)
```

---

## Task 1: 自建 Core 层 — Tool 抽象

**Files:**
- Create: `packages/server/core/__init__.py`
- Create: `packages/server/core/tool.py`
- Test: `tests/test_core_tool.py`

**说明:** 替代 SDK 的 `Tool`, `ToolInfo`, `Parameters`, `Param` 四个类。这是所有 14 个工具文件的基础依赖。

**Step 1: Write the failing test**

```python
# tests/test_core_tool.py
import pytest
from packages.server.core.tool import BaseTool, ToolParam

class EchoTool(BaseTool):
    name = "echo"
    description = "Echo input back"
    params = [
        ToolParam(name="message", description="Message to echo", param_type="string", required=True),
    ]

    async def execute(self, **kwargs) -> str:
        return kwargs["message"]

@pytest.mark.asyncio
async def test_tool_basic():
    tool = EchoTool()
    assert tool.name == "echo"
    result = await tool.execute(message="hello")
    assert result == "hello"

def test_tool_to_schema():
    tool = EchoTool()
    schema = tool.to_openai_schema()
    assert schema["type"] == "function"
    assert schema["function"]["name"] == "echo"
    assert "message" in schema["function"]["parameters"]["properties"]

def test_tool_param_required():
    tool = EchoTool()
    schema = tool.to_openai_schema()
    assert "message" in schema["function"]["parameters"]["required"]
```

**Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_core_tool.py -v`
Expected: FAIL — module not found

**Step 3: Write minimal implementation**

```python
# packages/server/core/tool.py
from dataclasses import dataclass, field
from typing import Any, Optional
from abc import ABC, abstractmethod

@dataclass
class ToolParam:
    """工具参数定义，替代 SDK 的 Param"""
    name: str
    description: str
    param_type: str = "string"  # string, integer, boolean, array, object
    required: bool = True
    default_value: Any = None
    enum: Optional[list] = None

class BaseTool(ABC):
    """工具基类，替代 SDK 的 Tool"""
    name: str = ""
    description: str = ""
    params: list[ToolParam] = []

    @abstractmethod
    async def execute(self, **kwargs) -> str:
        """执行工具，子类必须实现"""
        ...

    def to_openai_schema(self) -> dict:
        """转换为 OpenAI function calling 格式"""
        properties = {}
        required = []
        for p in self.params:
            prop = {"type": p.param_type, "description": p.description}
            if p.enum:
                prop["enum"] = p.enum
            properties[p.name] = prop
            if p.required:
                required.append(p.name)

        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": properties,
                    "required": required,
                },
            },
        }

    def to_anthropic_schema(self) -> dict:
        """转换为 Anthropic tool_use 格式"""
        schema = self.to_openai_schema()
        return {
            "name": schema["function"]["name"],
            "description": schema["function"]["description"],
            "input_schema": schema["function"]["parameters"],
        }
```

**Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_core_tool.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add packages/server/core/ tests/test_core_tool.py
git commit -m "feat: add BaseTool and ToolParam core abstractions"
```

---

## Task 2: 自建 Core 层 — LLM Client 抽象

**Files:**
- Create: `packages/server/core/llm.py`
- Test: `tests/test_core_llm.py`

**说明:** 统一的 LLM 调用接口，支持 Anthropic 和 OpenAI，替代 SDK 的 BaseModelInfo/ModelConfig。

**Step 1: Write the failing test**

```python
# tests/test_core_llm.py
import pytest
from packages.server.core.llm import LLMConfig, Message

def test_llm_config():
    config = LLMConfig(
        provider="anthropic",
        model="claude-sonnet-4-20250514",
        api_key="test-key",
    )
    assert config.provider == "anthropic"
    assert config.model == "claude-sonnet-4-20250514"

def test_message_creation():
    msg = Message(role="user", content="hello")
    assert msg.role == "user"
    assert msg.to_dict() == {"role": "user", "content": "hello"}

def test_message_with_tool_call():
    msg = Message(role="assistant", content="", tool_calls=[
        {"id": "1", "name": "read_file", "arguments": {"path": "/tmp/test"}}
    ])
    assert len(msg.tool_calls) == 1
```

**Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_core_llm.py -v`

**Step 3: Write minimal implementation**

```python
# packages/server/core/llm.py
from dataclasses import dataclass, field
from typing import Any, Optional

@dataclass
class LLMConfig:
    """LLM 配置，替代 SDK 的 BaseModelInfo + ModelConfig"""
    provider: str  # "anthropic" | "openai"
    model: str
    api_key: str
    api_base: Optional[str] = None
    temperature: float = 0.0
    max_tokens: int = 8192
    timeout: int = 120

@dataclass
class Message:
    """对话消息"""
    role: str  # "system" | "user" | "assistant" | "tool"
    content: str = ""
    tool_calls: list[dict] = field(default_factory=list)
    tool_call_id: Optional[str] = None
    name: Optional[str] = None

    def to_dict(self) -> dict:
        d = {"role": self.role, "content": self.content}
        if self.tool_calls:
            d["tool_calls"] = self.tool_calls
        if self.tool_call_id:
            d["tool_call_id"] = self.tool_call_id
        if self.name:
            d["name"] = self.name
        return d
```

**Step 4: Run test, Step 5: Commit**

```bash
git add packages/server/core/llm.py tests/test_core_llm.py
git commit -m "feat: add LLMConfig and Message core abstractions"
```

---

## Task 3: 自建 Core 层 — ReAct Agent 循环

**Files:**
- Create: `packages/server/core/react_loop.py`
- Test: `tests/test_react_loop.py`

**说明:** 这是最核心的部分。自建 ReAct 循环替代 SDK 的 ReActAgent。直接调用 Anthropic/OpenAI API，处理 tool_use 响应，循环执行直到完成。

**Step 1: Write the failing test**

```python
# tests/test_react_loop.py
import pytest
from unittest.mock import AsyncMock, MagicMock
from packages.server.core.react_loop import ReActLoop
from packages.server.core.tool import BaseTool, ToolParam
from packages.server.core.llm import LLMConfig

class MockTool(BaseTool):
    name = "greet"
    description = "Greet someone"
    params = [ToolParam(name="name", description="Name", param_type="string")]

    async def execute(self, **kwargs) -> str:
        return f"Hello, {kwargs['name']}!"

@pytest.mark.asyncio
async def test_react_loop_registers_tools():
    loop = ReActLoop(config=LLMConfig(provider="anthropic", model="test", api_key="test"))
    loop.add_tool(MockTool())
    assert "greet" in loop.tools

@pytest.mark.asyncio
async def test_react_loop_executes_tool():
    loop = ReActLoop(config=LLMConfig(provider="anthropic", model="test", api_key="test"))
    tool = MockTool()
    loop.add_tool(tool)
    result = await loop.execute_tool("greet", {"name": "World"})
    assert result == "Hello, World!"
```

**Step 2-5: Implement, test, commit**

核心实现要点：
- `ReActLoop` 类：管理工具注册、LLM 调用、tool_use 循环
- `run()` 方法：主循环 — 调用 LLM → 解析响应 → 如有 tool_use 则执行工具 → 将结果加入消息 → 继续循环
- `stream()` 方法：流式版本，yield 事件
- 最大迭代次数保护（防止无限循环）

```bash
git commit -m "feat: add ReActLoop - self-built ReAct agent core"
```

---

## Task 4: 复制无依赖模块 (Category A)

**Files:** 53 个文件，直接从 openjiuwen-code 复制

**说明:** 这些文件完全不依赖 SDK，可以原样复制。

**Step 1: 批量复制**

按模块分批复制：
- `packages/cli/` — CLI 入口和 TUI（需改品牌名）
- `packages/server/api/` — FastAPI + WebSocket
- `packages/server/skills/` — Skill 系统
- `packages/server/utils/` — 工具函数
- `packages/server/llm/` — LLM 路由
- `packages/server/agents/mode_manager.py` — 模式管理
- `packages/server/media/` — 媒体处理
- `packages/server/intent/` — 意图分类
- `packages/server/session/` — 会话管理
- `packages/server/interrupt/` — 中断处理
- `packages/server/context/` — 上下文管理
- `packages/server/edge_tts/` — TTS

**Step 2: 全局替换品牌名**

```
openjiuwen-code → lumos
openjiuwen_code → lumos
jiuwen → lumos
openJiuwen → Lumos
```

**Step 3: Commit**

```bash
git commit -m "feat: migrate SDK-independent modules from openjiuwen-code"
```

---

## Task 5: 迁移工具文件 (Category B)

**Files:** 14 个工具文件

**说明:** 所有工具的业务逻辑不变，只需要：
1. 将 `from openjiuwen.core.utils.tool.base import Tool` → `from packages.server.core.tool import BaseTool`
2. 将 `from openjiuwen.core.utils.tool.schema import ToolInfo, Parameters` → 删除（不再需要）
3. 将 `from openjiuwen.core.utils.tool.param import Param` → `from packages.server.core.tool import ToolParam`
4. 将工具类的基类从 `Tool` 改为 `BaseTool`
5. 将 `invoke()` / `ainvoke()` 方法重命名为 `execute()`

**Step 1: 复制所有工具文件**
**Step 2: 批量替换 import**
**Step 3: 逐个验证工具类签名**
**Step 4: Commit**

```bash
git commit -m "feat: migrate all tools with local BaseTool abstraction"
```

---

## Task 6: 重写 Agent 核心 (Category C)

**Files:**
- Create: `packages/server/agents/lumos_agent.py`
- Test: `tests/test_lumos_agent.py`

**说明:** 这是工作量最大的部分。用自建的 `ReActLoop` 替代 SDK 的 `ReActAgent`。

**从 openjiuwen_agent.py 中保留的逻辑：**
- 错误处理和重试机制
- 循环检测
- 模式切换 (BUILD/PLAN/REVIEW)
- Skill 管理
- 系统提示词构建
- 流式输出事件格式

**需要重写的逻辑：**
- Agent 初始化：不再用 `create_react_agent_config()`，直接构建 `ReActLoop`
- LLM 调用：不再通过 SDK，直接用 `anthropic.Client` / `openai.Client`
- 流式解析：不再解析 SDK 的 `OutputSchema`，直接解析 API 原生 stream
- 工具注册：不再用 `agent.add_tools()`，直接注册到 `ReActLoop`

**Step 1-5: TDD 实现**

```bash
git commit -m "feat: add LumosAgent - fully independent agent orchestrator"
```

---

## Task 7: CLI 入口适配

**Files:**
- Modify: `packages/cli/main.py`

**说明:**
- 移除 `setup_project_paths()` 中的 agent-core 路径设置
- 移除 SDK 日志抑制代码
- 将 `jiuwen` 品牌替换为 `lumos`
- 更新 `--version` 输出

```bash
git commit -m "feat: adapt CLI entry point for Lumos branding"
```

---

## Task 8: 配置文件和文档

**Files:**
- Create: `config/config.yaml`
- Create: `CLAUDE.md`
- Update: `pyproject.toml` (已完成)

**说明:**
- 配置文件去除 SDK 相关配置项
- CLAUDE.md 更新为 Lumos 项目说明
- 不再需要 SDK_CHANGES.md

```bash
git commit -m "docs: add Lumos configuration and project docs"
```

---

## Task 9: 测试迁移和验证

**Files:**
- Copy + adapt: `tests/` 目录

**说明:**
- 复制现有测试，更新 import 路径
- 确保单元测试全部通过
- E2E 测试需要 API Key 验证

```bash
git commit -m "test: migrate and adapt test suite for Lumos"
```

---

## 执行顺序依赖

```
Task 1 (Tool 抽象) ──┐
Task 2 (LLM 抽象) ───┤
                      ├→ Task 3 (ReAct Loop) → Task 6 (Agent 重写) → Task 7 (CLI)
Task 4 (复制 A 类) ───┤
                      └→ Task 5 (工具迁移) ─────────────────────────→ Task 8 (配置)
                                                                    → Task 9 (测试)
```

Task 1/2/4 可以并行，Task 3 依赖 1+2，Task 5 依赖 1，Task 6 依赖 3+4+5。
