"""
工具基类和模式感知的工具系统

实现模式感知的工具基类，所有工具都继承自此。
参考：docs/01-架构设计.md 第 1.4 节和 docs/02-详细技术设计.md 第 8.2 节
"""

from abc import ABC, abstractmethod
from typing import Dict, Any, Optional
from dataclasses import dataclass

from ..agents.mode_manager import AgentModeManager


@dataclass
class ToolInput:
    """工具输入数据"""
    data: Dict[str, Any]


@dataclass
class ToolOutput:
    """工具输出数据"""
    success: bool
    data: Optional[Any] = None
    error: Optional[str] = None


class ModePermissionError(Exception):
    """模式权限异常

    当工具在当前模式下不可用时抛出
    """
    pass


class BaseTool(ABC):
    """工具基类

    所有工具的抽象基类，提供工具的基本接口和模式感知功能。

    使用示例：
    >>> class ReadFileTool(BaseTool):
    >>>     def __init__(self, mode_manager):
    >>>         super().__init__(mode_manager)
    >>>         self.name = "read_file"
    >>>         self.required_permission = "read"
    >>>
    >>>     async def _execute(self, inputs):
    >>>         # 实现具体逻辑
    >>>         pass
    """

    def __init__(self, mode_manager: AgentModeManager):
        """初始化工具

        Args:
            mode_manager: 模式管理器实例
        """
        self.mode_manager = mode_manager
        self.name: str = ""
        self.description: str = ""
        self.required_permission: str = "read"  # read, write, execute

    async def ainvoke(self, inputs: ToolInput, **kwargs) -> ToolOutput:
        """异步调用接口（模式感知）

        在执行工具前会检查当前模式是否允许使用该工具。

        Args:
            inputs: 工具输入数据
            **kwargs: 额外的关键字参数

        Returns:
            ToolOutput: 工具执行结果
        """
        # 1. 检查工具权限
        tool_name = self.name
        if not self.mode_manager.is_tool_allowed(tool_name):
            return ToolOutput(
                success=False,
                error=f"工具 '{tool_name}' 在 {self.mode_manager.get_current_mode().value} 模式下不可用。"
            )

        # 2. 对于 Bash 工具，额外检查命令权限
        if tool_name == "bash" and "command" in inputs.data:
            command = inputs.data.get("command", "")
            if self.mode_manager.is_command_blocked(command):
                current_mode = self.mode_manager.get_current_mode().value
                return ToolOutput(
                    success=False,
                    error=f"命令在 {current_mode} 模式下被阻止（只读模式禁止修改操作）"
                )

        # 3. 执行工具逻辑
        try:
            return await self._execute(inputs, **kwargs)
        except Exception as e:
            return ToolOutput(
                success=False,
                error=f"工具执行失败: {str(e)}"
            )

    @abstractmethod
    async def _execute(self, inputs: ToolInput, **kwargs) -> ToolOutput:
        """执行工具的具体逻辑（子类实现）

        Args:
            inputs: 工具输入数据
            **kwargs: 额外的关键字参数

        Returns:
            ToolOutput: 工具执行结果
        """
        raise NotImplementedError

    def get_tool_info(self) -> Dict[str, Any]:
        """获取工具的元数据信息

        Returns:
            包含工具名称、描述等信息的字典
        """
        return {
            "name": self.name,
            "description": self.description,
            "required_permission": self.required_permission
        }


class ReadFileTool(BaseTool):
    """文件读取工具

    低层工具 - 用于读取文件内容
    """

    def __init__(self, mode_manager: AgentModeManager):
        super().__init__(mode_manager)
        self.name = "read_file"
        self.description = "读取文件内容。这是查看文件的主要工具。"
        self.required_permission = "read"

    async def _execute(self, inputs: ToolInput, **kwargs) -> ToolOutput:
        """执行文件读取

        Args:
            inputs: 包含 file_path, offset, limit 的输入

        Returns:
            ToolOutput: 包含文件内容或错误信息
        """
        file_path = inputs.data.get("file_path")
        offset = inputs.data.get("offset", 1)
        limit = inputs.data.get("limit")

        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                if offset > 1:
                    # 跳过前 offset-1 行
                    for _ in range(offset - 1):
                        f.readline()

                if limit:
                    lines = [f.readline() for _ in range(limit)]
                else:
                    lines = f.readlines()

            content = ''.join(lines)
            return ToolOutput(
                success=True,
                data={
                    "content": content,
                    "file_path": file_path,
                    "line_count": len(lines)
                }
            )

        except FileNotFoundError:
            return ToolOutput(
                success=False,
                error=f"文件不存在: {file_path}"
            )
        except Exception as e:
            return ToolOutput(
                success=False,
                error=f"读取文件失败: {str(e)}"
            )


class WriteFileTool(BaseTool):
    """文件写入工具

    低层工具 - 用于写入文件内容（仅 BUILD 模式）
    """

    def __init__(self, mode_manager: AgentModeManager):
        super().__init__(mode_manager)
        self.name = "write_file"
        self.description = "写入文件内容。如果文件已存在，将完全覆盖。"
        self.required_permission = "write"

    async def _execute(self, inputs: ToolInput, **kwargs) -> ToolOutput:
        """执行文件写入

        Args:
            inputs: 包含 file_path, content 的输入

        Returns:
            ToolOutput: 写入结果
        """
        file_path = inputs.data.get("file_path")
        content = inputs.data.get("content")

        try:
            # 创建父目录
            import os
            os.makedirs(os.path.dirname(file_path), exist_ok=True)

            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(content)

            return ToolOutput(
                success=True,
                data={
                    "file_path": file_path,
                    "bytes_written": len(content.encode('utf-8'))
                }
            )

        except Exception as e:
            return ToolOutput(
                success=False,
                error=f"写入文件失败: {str(e)}"
            )


class EditFileTool(BaseTool):
    """文件编辑工具

    中层工具 - 使用字符串替换编辑文件（仅 BUILD 模式）
    """

    def __init__(self, mode_manager: AgentModeManager):
        super().__init__(mode_manager)
        self.name = "edit_file"
        self.description = "编辑文件的指定部分。使用字符串替换方式修改文件。"
        self.required_permission = "write"

    async def _execute(self, inputs: ToolInput, **kwargs) -> ToolOutput:
        """执行文件编辑

        Args:
            inputs: 包含 file_path, old_string, new_string 的输入

        Returns:
            ToolOutput: 编辑结果
        """
        file_path = inputs.data.get("file_path")
        old_string = inputs.data.get("old_string")
        new_string = inputs.data.get("new_string")
        replace_all = inputs.data.get("replace_all", False)

        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()

            if old_string not in content:
                return ToolOutput(
                    success=False,
                    error=f"未找到要替换的字符串"
                )

            if replace_all:
                new_content = content.replace(old_string, new_string)
                count = content.count(old_string)
            else:
                new_content = content.replace(old_string, new_string, 1)
                count = 1

            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(new_content)

            return ToolOutput(
                success=True,
                data={
                    "file_path": file_path,
                    "replacements": count
                }
            )

        except Exception as e:
            return ToolOutput(
                success=False,
                error=f"编辑文件失败: {str(e)}"
            )
