"""
Lumos Core — Tool 抽象层

自建 Tool 抽象层，定义 BaseTool 和 ToolParam。
所有工具继承 BaseTool，实现 execute() 方法。
"""

from dataclasses import dataclass
from typing import Any, Optional
from abc import ABC, abstractmethod


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
    properties: dict = None
    required: list = None

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
    parameters: Parameters = None

    def __post_init__(self):
        if self.parameters is None:
            self.parameters = Parameters()


class LocalFunction:
    """SDK LocalFunction 兼容 shim (placeholder)"""
    pass
