"""
Lumos Core — Tool 抽象层

新接口：AgentTool + AgentToolResult（Pi Agent 风格）
旧接口：BaseTool + ToolParam（兼容层，供未迁移的工具文件使用）
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Awaitable, Optional, TYPE_CHECKING
from abc import ABC, abstractmethod

if TYPE_CHECKING:
    pass


@dataclass
class ToolParam:
    """工具参数定义，替代 SDK 的 Param"""
    name: str
    description: str
    param_type: str = "string"  # string, integer, boolean, number, array, object
    required: bool = True
    default_value: Any = None
    enum: Optional[list] = None
    items: Optional[dict] = None  # for array type
    properties: Optional[dict] = None  # for object type


class BaseTool(ABC):
    """工具基类，替代 SDK 的 Tool

    子类需要设置 name, description, params 类属性，
    并实现 execute() 异步方法。

    Example:
        class ReadFileTool(BaseTool):
            name = "read_file"
            description = "Read a file"
            params = [ToolParam(name="path", description="File path")]

            async def execute(self, **kwargs) -> str:
                ...
    """
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
            prop: dict[str, Any] = {"type": p.param_type, "description": p.description}
            if p.enum:
                prop["enum"] = p.enum
            if p.items and p.param_type == "array":
                prop["items"] = p.items
            if p.properties and p.param_type == "object":
                prop["properties"] = p.properties
            if p.default_value is not None:
                prop["default"] = p.default_value
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


# ============================================================================
# SDK 兼容层 — 保持迁移文件的业务逻辑不变
# ============================================================================

# Tool 别名：迁移文件中 class Foo(Tool) 继承自 SDK Tool，
# 现在指向本地 BaseTool
Tool = BaseTool

# Param 别名：迁移文件中大量使用 Param(name=..., description=..., ...)
Param = ToolParam


@dataclass
class Parameters:
    """SDK Parameters 兼容 shim"""
    type: str = "object"
    properties: Optional[dict] = None
    required: Optional[list] = None

    def __post_init__(self):
        if self.properties is None:
            self.properties = {}
        if self.required is None:
            self.required = []


@dataclass
class ToolInfo:
    """SDK ToolInfo 兼容 shim"""
    type: str = "function"
    name: str = ""
    description: str = ""
    parameters: Optional[Parameters] = None

    def __post_init__(self):
        if self.parameters is None:
            self.parameters = Parameters()


class LocalFunction:
    """SDK LocalFunction 兼容 shim (placeholder)"""
    pass


# ============================================================================
# 新接口 — Pi Agent 风格
# ============================================================================

@dataclass
class AgentToolResult:
    """工具执行结果（新接口）"""
    content: list = field(default_factory=list)  # list[TextContent | ImageContent]
    details: Any = None
    is_error: bool = False


# 工具执行函数签名
ExecuteFn = Callable[..., Awaitable[AgentToolResult]]


class AgentTool:
    """Pi Agent 风格的工具（新接口）

    不再使用类继承，而是组合模式：传入 execute_fn 即可。

    用法:
        async def _read_file(tool_call_id, params, **kwargs):
            ...
            return AgentToolResult(content=[TextContent(text=result)])

        read_file_tool = AgentTool(
            name="read_file",
            description="读取文件",
            parameters={"type": "object", "properties": {...}, "required": [...]},
            execute_fn=_read_file,
        )
    """

    def __init__(
        self,
        name: str,
        description: str,
        parameters: dict[str, Any],
        execute_fn: ExecuteFn,
        label: str = "",
    ):
        self.name = name
        self.description = description
        self.parameters = parameters  # JSON Schema dict
        self.label = label or name
        self._execute_fn = execute_fn

    async def execute(
        self,
        tool_call_id: str,
        params: dict[str, Any],
        signal: Any = None,
        on_update: Any = None,
    ) -> AgentToolResult:
        """执行工具"""
        return await self._execute_fn(
            tool_call_id, params, signal=signal, on_update=on_update
        )

    def to_schema(self) -> dict:
        """返回 Anthropic tool_use 格式 schema"""
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.parameters,
        }

    def to_openai_schema(self) -> dict:
        """返回 OpenAI function calling 格式 schema"""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }

    def to_anthropic_schema(self) -> dict:
        """to_schema 的别名"""
        return self.to_schema()


def wrap_legacy_tool(legacy_tool: BaseTool) -> AgentTool:
    """将旧 BaseTool 包装为新 AgentTool

    用于渐进式迁移：未改造的工具文件可以通过此函数桥接到新架构。
    支持两种旧工具模式：
    - ainvoke(inputs_dict) — lumos_tools.py 中的工具
    - execute(**params) — core/tool.py 中的 BaseTool 子类
    """
    from .types import TextContent

    async def _execute(tool_call_id: str, params: dict, **kwargs) -> AgentToolResult:
        # 优先使用 ainvoke（lumos_tools 中的工具用这个）
        ainvoke = getattr(legacy_tool, 'ainvoke', None)
        if ainvoke is not None and callable(ainvoke):
            result = await ainvoke(params)  # type: ignore[misc]
        else:
            result = await legacy_tool.execute(**params)  # type: ignore[misc]
        text = result if isinstance(result, str) else str(result)
        return AgentToolResult(content=[TextContent(text=text)])

    # 从旧 params 构建 JSON Schema
    schema = legacy_tool.to_anthropic_schema()

    return AgentTool(
        name=legacy_tool.name,
        description=legacy_tool.description,
        parameters=schema.get("input_schema", {"type": "object", "properties": {}, "required": []}),
        execute_fn=_execute,
        label=legacy_tool.name,
    )
