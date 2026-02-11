"""
搜索工具

实现基于 ripgrep 的内容搜索和文件模式匹配。
参考：docs/02-详细技术设计.md 第 1.3 节
"""

import asyncio
import os
from pathlib import Path
from typing import List, Dict, Any

from .base_tool import BaseTool, ToolInput, ToolOutput
from ..agents.mode_manager import AgentModeManager


class GrepTool(BaseTool):
    """内容搜索工具

    中层工具 - 基于 ripgrep 的内容搜索
    在所有模式下都可用（只读操作）
    """

    def __init__(self, mode_manager: AgentModeManager):
        super().__init__(mode_manager)
        self.name = "grep"
        self.description = "在文件中搜索内容。基于 ripgrep，支持正则表达式。"
        self.required_permission = "read"

    async def _execute(self, inputs: ToolInput, **kwargs) -> ToolOutput:
        """执行内容搜索

        Args:
            inputs: 包含 pattern, path, file_pattern, case_sensitive 的输入

        Returns:
            ToolOutput: 搜索结果
        """
        pattern = inputs.data.get("pattern", "")
        search_path = inputs.data.get("path", ".")
        file_pattern = inputs.data.get("file_pattern", "")
        case_sensitive = inputs.data.get("case_sensitive", False)
        context_lines = inputs.data.get("context_lines", 0)

        try:
            # 构建 ripgrep 命令
            cmd = ["rg", pattern, search_path]

            if not case_sensitive:
                cmd.append("-i")

            if file_pattern:
                cmd.extend(["-g", file_pattern])

            if context_lines > 0:
                cmd.extend(["-C", str(context_lines)])

            # 执行搜索
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )

            stdout, stderr = await process.communicate()

            if process.returncode == 0:
                # 成功
                results = stdout.decode('utf-8', errors='replace')
                return ToolOutput(
                    success=True,
                    data={
                        "matches": results,
                        "pattern": pattern,
                        "path": search_path,
                        "count": results.count('\n')
                    }
                )
            else:
                # 没有匹配或其他错误
                stderr_text = stderr.decode('utf-8', errors='replace')
                if process.returncode == 1:
                    # ripgrep 返回 1 表示没有匹配
                    return ToolOutput(
                        success=True,
                        data={
                            "matches": "",
                            "pattern": pattern,
                            "path": search_path,
                            "count": 0
                        }
                    )
                else:
                    return ToolOutput(
                        success=False,
                        error=f"搜索失败: {stderr_text}"
                    )

        except FileNotFoundError:
            # ripgrep 未安装
            return ToolOutput(
                success=False,
                error="ripgrep (rg) 未安装。请先安装: apt install ripgrep"
            )
        except Exception as e:
            return ToolOutput(
                success=False,
                error=f"搜索执行失败: {str(e)}"
            )


class GlobTool(BaseTool):
    """文件模式匹配工具

    中层工具 - 使用 glob 模式查找文件
    在所有模式下都可用（只读操作）
    """

    def __init__(self, mode_manager: AgentModeManager):
        super().__init__(mode_manager)
        self.name = "glob"
        self.description = "使用 glob 模式查找文件。支持 ** 和 * 通配符。"
        self.required_permission = "read"

    async def _execute(self, inputs: ToolInput, **kwargs) -> ToolOutput:
        """执行文件模式匹配

        Args:
            inputs: 包含 pattern, path 的输入

        Returns:
            ToolOutput: 匹配的文件列表
        """
        pattern = inputs.data.get("pattern", "")
        search_path = inputs.data.get("path", ".")

        try:
            # 使用 pathlib 进行 glob 匹配
            base_path = Path(search_path)
            matched_files = list(base_path.glob(pattern))

            # 转换为相对路径
            relative_paths = []
            for file_path in matched_files:
                if file_path.is_file():
                    try:
                        rel_path = file_path.relative_to(search_path)
                        relative_paths.append(str(rel_path))
                    except ValueError:
                        # 无法转换为相对路径，使用绝对路径
                        relative_paths.append(str(file_path))

            # 排序
            relative_paths.sort()

            return ToolOutput(
                success=True,
                data={
                    "files": relative_paths,
                    "pattern": pattern,
                    "path": search_path,
                    "count": len(relative_paths)
                }
            )

        except Exception as e:
            return ToolOutput(
                success=False,
                error=f"文件匹配失败: {str(e)}"
            )
