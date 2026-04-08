"""
lumos SDK 兼容的工具实现

基于 lumos agent-core SDK 的 Tool 接口实现工具集
"""

import os
import asyncio
import subprocess
from typing import List, Optional
from ..core.tool import Tool, ToolInfo, Parameters, Param, AgentTool, wrap_legacy_tool

from ..agents.mode_manager import AgentModeManager, AgentMode
from ..utils.platform_compat import (
    get_blacklisted_commands,
    get_plan_mode_blocked_patterns,
    get_plan_mode_blocked_script_patterns,
)


# ==================== 工具结果截断辅助函数 ====================

def truncate_tool_result(result: str, max_length: int = 8000) -> str:
    """截断过长的工具结果以避免 API 400 错误

    Args:
        result: 工具执行结果
        max_length: 最大长度（默认 8000 字符，更保守的限制）

    Returns:
        截断后的结果
    """
    if len(result) <= max_length:
        return result

    truncated = result[:max_length]
    truncated += f"\n\n... [结果过长，已截断 {len(result) - max_length} 字符]"
    return truncated


# ==================== ReadFile ====================

class ReadFileTool(Tool):
    """文件读取工具

    低层工具 - 用于读取文件内容，支持文本文件和 PDF 文件
    """

    def __init__(self, mode_manager: Optional[AgentModeManager] = None):
        super().__init__()
        self.mode_manager = mode_manager
        self.name = "read_file"
        self.description = """读取文件内容。这是查看文件的主要工具。

使用说明:
- 用于读取任意文本文件内容
- 支持读取 PDF 文件（自动提取文本）
- 支持指定行号范围读取大文件
- 返回带行号的文件内容

参数:
- file_path: 要读取的文件路径（必需）
- offset: 开始读取的行号（默认1）
- limit: 读取的最大行数（可选）
"""
        self.params = [
            Param(name="file_path", description="要读取的文件路径", param_type="string", required=True),
            Param(name="offset", description="开始读取的行号（默认1）", param_type="integer", required=False, default_value=1),
            Param(name="limit", description="读取的最大行数", param_type="integer", required=False),
        ]
    
    def invoke(self, inputs: dict, **kwargs) -> str:
        """同步调用"""
        return asyncio.run(self.ainvoke(inputs, **kwargs))
    
    async def ainvoke(self, inputs: dict, **kwargs) -> str:
        """异步调用"""
        file_path = inputs.get("file_path")
        offset = inputs.get("offset", 1)
        limit = inputs.get("limit")

        if not file_path:
            return "错误: 未指定文件路径"

        # 检查是否是 PDF 文件
        if file_path.lower().endswith('.pdf'):
            return await self._read_pdf(file_path, offset, limit)

        # 读取普通文本文件
        return await self._read_text_file(file_path, offset, limit)

    async def _read_pdf(self, file_path: str, offset: int, limit: Optional[int] = None) -> str:
        """读取 PDF 文件"""
        try:
            import pdfplumber
        except ImportError:
            return "错误: 需要安装 pdfplumber 库来读取 PDF。请运行: pip install pdfplumber"

        try:
            text_lines = []
            with pdfplumber.open(file_path) as pdf:
                for i, page in enumerate(pdf.pages):
                    page_text = page.extract_text()
                    if page_text:
                        text_lines.append(f"--- 第 {i+1} 页 ---")
                        text_lines.extend(page_text.split('\n'))

            if not text_lines:
                return f"PDF 文件 {file_path} 没有可提取的文本内容"

            total_lines = len(text_lines)
            start_idx = max(0, offset - 1)
            end_idx = min(start_idx + limit, total_lines) if limit else total_lines
            selected_lines = text_lines[start_idx:end_idx]

            numbered_lines = []
            for i, line in enumerate(selected_lines, start=start_idx + 1):
                numbered_lines.append(f"{i:6}|{line}")

            result = "\n".join(numbered_lines)
            header = f"PDF文件: {file_path} (行 {start_idx + 1}-{end_idx}/{total_lines})\n"
            return truncate_tool_result(header + result)

        except FileNotFoundError:
            return f"错误: 文件不存在 - {file_path}"
        except Exception as e:
            return f"错误: 读取 PDF 失败 - {str(e)}"

    async def _read_text_file(self, file_path: str, offset: int, limit: Optional[int] = None) -> str:
        """读取普通文本文件"""
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                all_lines = f.readlines()
            
            total_lines = len(all_lines)
            
            # 处理偏移量
            start_idx = max(0, offset - 1)
            
            # 处理限制
            if limit:
                end_idx = min(start_idx + limit, total_lines)
            else:
                end_idx = total_lines
            
            selected_lines = all_lines[start_idx:end_idx]
            
            # 添加行号
            numbered_lines = []
            for i, line in enumerate(selected_lines, start=start_idx + 1):
                numbered_lines.append(f"{i:6}|{line.rstrip()}")
            
            result = "\n".join(numbered_lines)

            # 添加文件信息
            header = f"文件: {file_path} (行 {start_idx + 1}-{end_idx}/{total_lines})\n"

            full_result = header + result

            # 截断过长的结果
            return truncate_tool_result(full_result)
            
        except FileNotFoundError:
            return f"错误: 文件不存在 - {file_path}"
        except Exception as e:
            return f"错误: 读取文件失败 - {str(e)}"
    
    def get_tool_info(self) -> ToolInfo:
        """获取工具信息"""
        return ToolInfo(
            type="function",
            name=self.name,
            description=self.description,
            parameters=Parameters(
                type="object",
                properties={
                    "file_path": {"type": "string", "description": "要读取的文件路径"},
                    "offset": {"type": "integer", "description": "开始读取的行号（默认1）"},
                    "limit": {"type": "integer", "description": "读取的最大行数"}
                },
                required=["file_path"]
            )
        )


# ==================== WriteFile ====================

class WriteFileTool(Tool):
    """文件写入工具
    
    低层工具 - 用于写入文件内容（仅 BUILD 模式）
    """
    
    def __init__(self, mode_manager: Optional[AgentModeManager] = None):
        super().__init__()
        self.mode_manager = mode_manager
        self.name = "write_file"
        self.description = """写入文件内容。如果文件已存在，将完全覆盖。

使用说明:
- 用于创建新文件或完全覆盖现有文件
- 自动创建不存在的目录
- 仅在 BUILD 模式下可用

参数:
- file_path: 要写入的文件路径（必需）
- content: 要写入的内容（必需）
"""
        self.params = [
            Param(name="file_path", description="要写入的文件路径", param_type="string", required=True),
            Param(name="content", description="要写入的内容", param_type="string", required=True),
        ]

    def _is_plan_file(self, file_path: str) -> bool:
        """检查是否是 plan 文件（~/.lumos/plans/ 目录下的文件）"""
        if not file_path:
            return False
        # 规范化路径
        normalized_path = os.path.normpath(os.path.expanduser(file_path))
        plans_dir = os.path.normpath(os.path.expanduser("~/.lumos/plans"))
        # 检查是否在 plans 目录下
        return normalized_path.startswith(plans_dir)

    def invoke(self, inputs: dict, **kwargs) -> str:
        """同步调用"""
        return asyncio.run(self.ainvoke(inputs, **kwargs))
    
    def _detect_corrupted_json_format(self, content: str) -> bool:
        """检测内容是否为损坏的 JSON 格式。

        某些模型（如智谱 GLM）可能会生成损坏的 JSON 格式的代码内容，
        例如 [[], {...}] 这种无法恢复的格式。

        Args:
            content: 要检测的内容

        Returns:
            True 如果内容是损坏的格式，False 否则
        """
        # 检测损坏的 JSON 数组格式
        # 模式: [[], {"key": "value", ...}] - 代码被错误地序列化为 JSON
        if content.startswith('[[], {') or content.startswith('[[],{'):
            return True

        # 检测代码中包含明显的 JSON 键值对模式
        # 例如: [[], {"pdf_file.name}": "with pdfplumber...
        if content.startswith('[[]') and '": "' in content[:100]:
            return True

        return False

    def _detect_and_fix_json_array_format(
        self, content: str
    ) -> tuple[str, bool, str]:
        """检测并修复被错误包装为 JSON 数组的内容

        有时模型会发送类似 [[], ["code..."]] 格式的内容

        Args:
            content: 原始内容

        Returns:
            (处理后的内容, 是否进行了修复, 错误消息（如果有）)
        """
        import json

        # 首先检测不可恢复的损坏格式
        if self._detect_corrupted_json_format(content):
            error_msg = (
                "错误: 代码内容格式损坏。检测到 [[], {...}] 格式，"
                "这通常是模型输出错误导致的。"
                "请重新生成代码，确保 content 参数是纯文本的代码字符串，"
                "而不是 JSON 数组或对象格式。"
            )
            return content, False, error_msg

        # 检测常见的错误模式
        # 1. 以 [[ 开头，以 ]] 结尾
        if content.startswith('[[') and content.endswith(']]'):
            try:
                # 尝试解析为 JSON
                parsed = json.loads(content)
                if isinstance(parsed, list):
                    # 尝试提取实际内容
                    for item in parsed:
                        if isinstance(item, list):
                            for sub_item in item:
                                if isinstance(sub_item, str) and len(sub_item) > 50:
                                    return sub_item, True, ""
                        elif isinstance(item, str) and len(item) > 50:
                            return item, True, ""
            except (json.JSONDecodeError, TypeError):
                pass

        # 2. 以 [[], [" 开头 - 这是错误的 JSON 格式
        if content.startswith('[[], ["'):
            # 尝试提取引号中的内容
            try:
                # 去掉开头的 [[], ["
                rest = content[7:]
                # 去掉结尾的 "]]
                if rest.endswith('"]]'):
                    rest = rest[:-3]
                # 处理转义
                rest = rest.replace('\\"', '"')
                if len(rest) > 50:
                    return rest, True, ""
            except Exception:
                pass

        return content, False, ""

    def _normalize_escape_sequences(
        self, content: str
    ) -> tuple[str, bool, str]:
        """规范化转义序列

        处理模型可能发送的字面量转义字符（如 '\\n' 而非实际换行）

        Args:
            content: 原始内容

        Returns:
            (处理后的内容, 是否进行了转换, 错误消息（如果有）)
        """
        converted = False

        # 首先检测并修复 JSON 数组格式问题
        content, json_fixed, error_msg = self._detect_and_fix_json_array_format(
            content
        )
        if error_msg:
            return content, False, error_msg
        if json_fixed:
            converted = True

        # 检测模式：如果内容很长但没有实际换行，可能是转义问题
        # 仅当内容超过 200 字符且只有一行时才处理
        if len(content) > 200 and '\n' not in content:
            # 检查是否包含字面量的 \n（JSON 转义形式）
            if '\\n' in content:
                content = content.replace('\\n', '\n')
                converted = True
            if '\\t' in content:
                content = content.replace('\\t', '\t')
                converted = True
            if '\\r' in content:
                content = content.replace('\\r', '\r')
                converted = True

        return content, converted, ""

    async def ainvoke(self, inputs: dict, **kwargs) -> str:
        """异步调用"""
        file_path = inputs.get("file_path")

        # 检查模式权限（允许在 PLAN 模式下编辑 plan 文件）
        if self.mode_manager and self.mode_manager.get_current_mode() != AgentMode.BUILD:
            # 允许编辑 ~/.lumos/plans/ 目录下的 plan 文件
            if file_path and self._is_plan_file(file_path):
                pass  # 允许编辑 plan 文件
            else:
                return f"错误: write_file 工具在 {self.mode_manager.get_current_mode().value} 模式下不可用。请切换到 BUILD 模式。"
        content = inputs.get("content", "")

        if not file_path:
            return "错误: 未指定文件路径"

        try:
            # 规范化转义序列（处理模型可能发送的 \\n 等字面量）
            content, escape_converted, format_error = (
                self._normalize_escape_sequences(content)
            )

            # 如果检测到格式错误，返回错误消息让模型重试
            if format_error:
                return format_error

            # 检查文件是否已存在（用于区分 Write/Update）
            file_exists = os.path.exists(file_path)

            # 创建目录
            dir_path = os.path.dirname(file_path)
            if dir_path:
                os.makedirs(dir_path, exist_ok=True)

            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(content)

            # 计算行数和生成预览
            lines = content.split('\n')
            line_count = len(lines)
            preview_lines = lines[:10]
            preview = '\n'.join(
                f"     {i+1} {line}" for i, line in enumerate(preview_lines)
            )
            remaining = line_count - 10 if line_count > 10 else 0

            # 返回结构化信息
            action = "Updated" if file_exists else "Wrote"
            result = f"{action} {line_count} lines to {file_path}\n{preview}"
            if remaining > 0:
                result += f"\n    … +{remaining} lines"

            # 如果进行了转义转换，添加提示
            if escape_converted:
                result += (
                    "\n\n[注意: 已自动将 \\\\n 转义字符转换为实际换行符]"
                )

            return result

        except Exception as e:
            return f"错误: 写入文件失败 - {str(e)}"
    
    def get_tool_info(self) -> ToolInfo:
        """获取工具信息"""
        return ToolInfo(
            type="function",
            name=self.name,
            description=self.description,
            parameters=Parameters(
                type="object",
                properties={
                    "file_path": {"type": "string", "description": "要写入的文件路径"},
                    "content": {"type": "string", "description": "要写入的内容"}
                },
                required=["file_path", "content"]
            )
        )


# ==================== EditFile ====================

class EditFileTool(Tool):
    """文件编辑工具
    
    中层工具 - 使用字符串替换编辑文件（仅 BUILD 模式）
    """
    
    def __init__(self, mode_manager: Optional[AgentModeManager] = None):
        super().__init__()
        self.mode_manager = mode_manager
        self.name = "edit_file"
        self.description = """编辑文件的指定部分。使用字符串替换方式修改文件。

使用说明:
- 用于精确修改文件中的特定内容
- old_string 必须在文件中唯一存在
- 仅在 BUILD 模式下可用

参数:
- file_path: 要编辑的文件路径（必需）
- old_string: 要替换的原始字符串（必需）
- new_string: 替换后的新字符串（必需）
- replace_all: 是否替换所有匹配项（默认 false）
"""
        self.params = [
            Param(name="file_path", description="要编辑的文件路径", param_type="string", required=True),
            Param(name="old_string", description="要替换的原始字符串", param_type="string", required=True),
            Param(name="new_string", description="替换后的新字符串", param_type="string", required=True),
            Param(name="replace_all", description="是否替换所有匹配项", param_type="boolean", required=False, default_value=False),
        ]

    def _is_plan_file(self, file_path: str) -> bool:
        """检查是否是 plan 文件（~/.lumos/plans/ 目录下的文件）"""
        if not file_path:
            return False
        # 规范化路径
        normalized_path = os.path.normpath(os.path.expanduser(file_path))
        plans_dir = os.path.normpath(os.path.expanduser("~/.lumos/plans"))
        # 检查是否在 plans 目录下
        return normalized_path.startswith(plans_dir)

    def invoke(self, inputs: dict, **kwargs) -> str:
        """同步调用"""
        return asyncio.run(self.ainvoke(inputs, **kwargs))

    async def ainvoke(self, inputs: dict, **kwargs) -> str:
        """异步调用"""
        file_path = inputs.get("file_path")

        # 检查模式权限（允许在 PLAN 模式下编辑 plan 文件）
        if self.mode_manager and self.mode_manager.get_current_mode() != AgentMode.BUILD:
            # 允许编辑 ~/.lumos/plans/ 目录下的 plan 文件
            if file_path and self._is_plan_file(file_path):
                pass  # 允许编辑 plan 文件
            else:
                return f"错误: edit_file 工具在 {self.mode_manager.get_current_mode().value} 模式下不可用。请切换到 BUILD 模式。"

        old_string = inputs.get("old_string")
        new_string = inputs.get("new_string", "")
        replace_all = inputs.get("replace_all", False)
        
        if not file_path:
            return "错误: 未指定文件路径"
        if old_string is None:
            return "错误: 未指定要替换的字符串"
        
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            if old_string not in content:
                return f"错误: 未在文件中找到要替换的字符串"
            
            # 计算匹配数量
            count = content.count(old_string)
            
            if replace_all:
                new_content = content.replace(old_string, new_string)
                replaced_count = count
            else:
                new_content = content.replace(old_string, new_string, 1)
                replaced_count = 1
            
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(new_content)
            
            return f"成功编辑 {file_path}，替换了 {replaced_count} 处"
            
        except FileNotFoundError:
            return f"错误: 文件不存在 - {file_path}"
        except Exception as e:
            return f"错误: 编辑文件失败 - {str(e)}"
    
    def get_tool_info(self) -> ToolInfo:
        """获取工具信息"""
        return ToolInfo(
            type="function",
            name=self.name,
            description=self.description,
            parameters=Parameters(
                type="object",
                properties={
                    "file_path": {"type": "string", "description": "要编辑的文件路径"},
                    "old_string": {"type": "string", "description": "要替换的原始字符串"},
                    "new_string": {"type": "string", "description": "替换后的新字符串"},
                    "replace_all": {"type": "boolean", "description": "是否替换所有匹配项"}
                },
                required=["file_path", "old_string", "new_string"]
            )
        )


# ==================== BashTool ====================

class BashTool(Tool):
    """Shell 命令执行工具

    低层工具 - 执行 Shell 命令
    """

    # 类属性：黑名单命令（向后兼容）
    BLOCKED_COMMANDS = get_blacklisted_commands()

    def __init__(self, mode_manager: Optional[AgentModeManager] = None):
        super().__init__()
        self.mode_manager = mode_manager
        self.name = "bash"
        self.description = """执行 Shell 命令。

使用说明:
- 用于执行任意 shell 命令
- 在 PLAN 模式下，某些修改命令会被禁止
- 有超时限制（默认 30 秒）
- 在 PLAN 模式下允许写入 ~/.lumos/plans/ 目录下的 plan 文件

参数:
- command: 要执行的命令（必需）
- timeout: 超时时间（秒，默认 30）
"""
        self.params = [
            Param(name="command", description="要执行的 Shell 命令", param_type="string", required=True),
            Param(name="timeout", description="超时时间（秒）", param_type="integer", required=False, default_value=30),
        ]
        # 加载平台特定的安全配置
        self._blocked_commands = get_blacklisted_commands()
        self._plan_blocked_patterns = get_plan_mode_blocked_patterns()
        self._plan_blocked_scripts = get_plan_mode_blocked_script_patterns()

    def _is_plan_file_operation(self, command: str) -> bool:
        """检查命令是否是对 plan 文件的操作（~/.lumos/plans/ 目录下的文件）"""
        if not command:
            return False
        # 获取 plans 目录路径
        plans_dir = os.path.expanduser("~/.lumos/plans")
        # 检查命令是否涉及 plans 目录
        return plans_dir in command or ".lumos/plans" in command

    def invoke(self, inputs: dict, **kwargs) -> str:
        """同步调用"""
        return asyncio.run(self.ainvoke(inputs, **kwargs))
    
    async def ainvoke(self, inputs: dict, **kwargs) -> str:
        """异步调用"""
        command = inputs.get("command", "")
        timeout = inputs.get("timeout", 30)

        if not command:
            return "错误: 未指定命令"

        # 检查黑名单
        for blocked in self._blocked_commands:
            if blocked in command:
                return f"错误: 命令被禁止执行（安全限制）"

        # 检查模式限制（支持权限预授权）
        if self.mode_manager and self.mode_manager.get_current_mode() != AgentMode.BUILD:
            current_mode = self.mode_manager.get_current_mode()

            # 检查是否是 plan 文件操作（允许在 PLAN 模式下编辑 plan 文件）
            is_plan_file_op = self._is_plan_file_operation(command)

            # 检查是否有预授权
            from .plan_tools import get_permission_manager
            permission_manager = get_permission_manager()

            is_preauthorized = permission_manager.is_command_preauthorized(command)

            if not is_preauthorized and not is_plan_file_op:
                # 首先检查脚本执行模式（防止绕过）
                for pattern in self._plan_blocked_scripts:
                    if pattern in command:
                        return f"错误: 在 {current_mode.value} 模式下禁止执行脚本命令（'{pattern}'）。这是为了防止绕过安全限制。请切换到 BUILD 模式。"

                # 然后检查常规禁止模式
                for pattern in self._plan_blocked_patterns:
                    if pattern in command:
                        matching_prompt = permission_manager.get_matching_prompt(command)
                        if matching_prompt:
                            # 命令已预授权，允许执行
                            break
                        return f"错误: 命令 '{pattern.strip()}' 在 {current_mode.value} 模式下被禁止。请切换到 BUILD 模式或在 Plan 审批时预授权此命令。"
        
        try:
            # 执行命令
            process = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=os.getcwd()
            )
            
            try:
                stdout, stderr = await asyncio.wait_for(
                    process.communicate(),
                    timeout=timeout
                )
            except asyncio.TimeoutError:
                process.kill()
                return f"错误: 命令执行超时（{timeout}秒）"
            
            exit_code = process.returncode
            stdout_str = stdout.decode('utf-8', errors='replace')
            stderr_str = stderr.decode('utf-8', errors='replace')

            # 构建结果
            result_parts = []
            if stdout_str:
                result_parts.append(f"stdout:\n{stdout_str}")
            if stderr_str:
                result_parts.append(f"stderr:\n{stderr_str}")
            result_parts.append(f"exit_code: {exit_code}")

            full_result = "\n".join(result_parts)

            # 截断过长的结果
            return truncate_tool_result(full_result)
            
        except Exception as e:
            return f"错误: 命令执行失败 - {str(e)}"
    
    def get_tool_info(self) -> ToolInfo:
        """获取工具信息"""
        return ToolInfo(
            type="function",
            name=self.name,
            description=self.description,
            parameters=Parameters(
                type="object",
                properties={
                    "command": {"type": "string", "description": "要执行的 Shell 命令"},
                    "timeout": {"type": "integer", "description": "超时时间（秒）"}
                },
                required=["command"]
            )
        )


# ==================== GrepTool ====================

class GrepTool(Tool):
    """内容搜索工具
    
    中层工具 - 使用 ripgrep 进行内容搜索
    """
    
    def __init__(self, mode_manager: Optional[AgentModeManager] = None):
        super().__init__()
        self.mode_manager = mode_manager
        self.name = "grep"
        self.description = """在文件中搜索内容。基于 ripgrep，速度快且支持正则表达式。

使用说明:
- 用于在文件或目录中搜索特定内容
- 支持正则表达式
- 所有模式下可用

参数:
- pattern: 搜索模式（正则表达式）（必需）
- path: 搜索路径（文件或目录）（必需）
- ignore_case: 忽略大小写（默认 false）
"""
        self.params = [
            Param(name="pattern", description="搜索模式（正则表达式）", param_type="string", required=True),
            Param(name="path", description="搜索路径", param_type="string", required=True),
            Param(name="ignore_case", description="忽略大小写", param_type="boolean", required=False, default_value=False),
        ]
    
    def invoke(self, inputs: dict, **kwargs) -> str:
        """同步调用"""
        return asyncio.run(self.ainvoke(inputs, **kwargs))
    
    async def ainvoke(self, inputs: dict, **kwargs) -> str:
        """异步调用"""
        pattern = inputs.get("pattern", "")
        path = inputs.get("path", ".")
        ignore_case = inputs.get("ignore_case", False)
        
        if not pattern:
            return "错误: 未指定搜索模式"
        
        # 展开 ~ 符号为用户家目录
        path = os.path.expanduser(path)
        
        # 构建命令
        cmd_parts = ["rg", "--line-number", "--color=never"]
        if ignore_case:
            cmd_parts.append("-i")
        cmd_parts.extend([pattern, path])
        
        try:
            process = await asyncio.create_subprocess_exec(
                *cmd_parts,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            
            stdout, stderr = await asyncio.wait_for(
                process.communicate(),
                timeout=30
            )
            
            stdout_str = stdout.decode('utf-8', errors='replace')
            stderr_str = stderr.decode('utf-8', errors='replace')

            if process.returncode == 0:
                result = stdout_str if stdout_str else "未找到匹配结果"
                return truncate_tool_result(result)
            elif process.returncode == 1:
                return "未找到匹配结果"
            else:
                # 如果 rg 不可用，回退到 grep
                return await self._fallback_grep(pattern, path, ignore_case)
                
        except FileNotFoundError:
            # ripgrep 不存在，使用 grep 回退
            return await self._fallback_grep(pattern, path, ignore_case)
        except Exception as e:
            return f"错误: 搜索失败 - {str(e)}"
    
    async def _fallback_grep(self, pattern: str, path: str, ignore_case: bool) -> str:
        """使用 grep 作为回退"""
        cmd_parts = ["grep", "-rn"]
        if ignore_case:
            cmd_parts.append("-i")
        cmd_parts.extend([pattern, path])
        
        try:
            process = await asyncio.create_subprocess_exec(
                *cmd_parts,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            
            stdout, _ = await asyncio.wait_for(
                process.communicate(),
                timeout=30
            )

            stdout_str = stdout.decode('utf-8', errors='replace')
            result = stdout_str if stdout_str else "未找到匹配结果"
            return truncate_tool_result(result)
            
        except Exception as e:
            return f"错误: 搜索失败 - {str(e)}"
    
    def get_tool_info(self) -> ToolInfo:
        """获取工具信息"""
        return ToolInfo(
            type="function",
            name=self.name,
            description=self.description,
            parameters=Parameters(
                type="object",
                properties={
                    "pattern": {"type": "string", "description": "搜索模式（正则表达式）"},
                    "path": {"type": "string", "description": "搜索路径"},
                    "ignore_case": {"type": "boolean", "description": "忽略大小写"}
                },
                required=["pattern", "path"]
            )
        )


# ==================== GlobTool ====================

class GlobTool(Tool):
    """文件模式匹配工具
    
    中层工具 - 使用 glob 模式查找文件
    """
    
    def __init__(self, mode_manager: Optional[AgentModeManager] = None):
        super().__init__()
        self.mode_manager = mode_manager
        self.name = "glob"
        self.description = """使用 glob 模式查找文件。

使用说明:
- 用于按文件名模式查找文件
- 支持 *, **, ? 等通配符
- 所有模式下可用

参数:
- pattern: glob 模式（必需）
- path: 搜索根目录（默认当前目录）
"""
        self.params = [
            Param(name="pattern", description="glob 模式（如 *.py, **/*.js）", param_type="string", required=True),
            Param(name="path", description="搜索根目录", param_type="string", required=False, default_value="."),
        ]
    
    def invoke(self, inputs: dict, **kwargs) -> str:
        """同步调用"""
        return asyncio.run(self.ainvoke(inputs, **kwargs))
    
    async def ainvoke(self, inputs: dict, **kwargs) -> str:
        """异步调用"""
        import glob as glob_module
        
        pattern = inputs.get("pattern", "")
        path = inputs.get("path", ".")
        
        if not pattern:
            return "错误: 未指定 glob 模式"
        
        # 展开 ~ 符号为用户家目录
        path = os.path.expanduser(path)
        
        try:
            # 处理相对路径
            if not os.path.isabs(path):
                path = os.path.abspath(path)
            
            # 组合完整模式
            full_pattern = os.path.join(path, pattern)
            
            # 使用 glob 查找
            files = glob_module.glob(full_pattern, recursive=True)
            
            if not files:
                return f"未找到匹配 '{pattern}' 的文件"
            
            # 排序并格式化结果
            files.sort()
            result_lines = [f"找到 {len(files)} 个文件:"]
            for f in files[:100]:  # 限制最多显示 100 个
                result_lines.append(f"  {f}")
            
            if len(files) > 100:
                result_lines.append(f"  ... 还有 {len(files) - 100} 个文件")
            
            return "\n".join(result_lines)
            
        except Exception as e:
            return f"错误: 查找文件失败 - {str(e)}"
    
    def get_tool_info(self) -> ToolInfo:
        """获取工具信息"""
        return ToolInfo(
            type="function",
            name=self.name,
            description=self.description,
            parameters=Parameters(
                type="object",
                properties={
                    "pattern": {"type": "string", "description": "glob 模式（如 *.py, **/*.js）"},
                    "path": {"type": "string", "description": "搜索根目录"}
                },
                required=["pattern"]
            )
        )


# ==================== ListDirTool ====================

class ListDirTool(Tool):
    """目录列表工具
    
    中层工具 - 列出目录内容
    """
    
    def __init__(self, mode_manager: Optional[AgentModeManager] = None):
        super().__init__()
        self.mode_manager = mode_manager
        self.name = "ls"
        self.description = """列出目录内容。

使用说明:
- 用于查看目录中的文件和子目录
- 所有模式下可用

参数:
- path: 目录路径（默认当前目录）
- show_hidden: 显示隐藏文件（默认 false）
"""
        self.params = [
            Param(name="path", description="目录路径", param_type="string", required=False, default_value="."),
            Param(name="show_hidden", description="显示隐藏文件", param_type="boolean", required=False, default_value=False),
        ]
    
    def invoke(self, inputs: dict, **kwargs) -> str:
        """同步调用"""
        return asyncio.run(self.ainvoke(inputs, **kwargs))
    
    async def ainvoke(self, inputs: dict, **kwargs) -> str:
        """异步调用"""
        path = inputs.get("path", ".")
        show_hidden = inputs.get("show_hidden", False)
        
        # 展开 ~ 符号为用户家目录
        path = os.path.expanduser(path)
        
        try:
            if not os.path.exists(path):
                return f"错误: 路径不存在 - {path}"
            
            if not os.path.isdir(path):
                return f"错误: 不是目录 - {path}"
            
            entries = os.listdir(path)
            
            # 过滤隐藏文件
            if not show_hidden:
                entries = [e for e in entries if not e.startswith('.')]
            
            # 分类排序
            dirs = []
            files = []
            
            for entry in entries:
                full_path = os.path.join(path, entry)
                if os.path.isdir(full_path):
                    dirs.append(entry + "/")
                else:
                    files.append(entry)
            
            dirs.sort()
            files.sort()
            
            # 格式化输出
            result_lines = [f"目录: {os.path.abspath(path)}"]
            
            if dirs:
                result_lines.append("\n目录:")
                for d in dirs:
                    result_lines.append(f"  📁 {d}")
            
            if files:
                result_lines.append("\n文件:")
                for f in files:
                    result_lines.append(f"  📄 {f}")
            
            if not dirs and not files:
                result_lines.append("\n(空目录)")
            
            return "\n".join(result_lines)
            
        except Exception as e:
            return f"错误: 列出目录失败 - {str(e)}"
    
    def get_tool_info(self) -> ToolInfo:
        """获取工具信息"""
        return ToolInfo(
            type="function",
            name=self.name,
            description=self.description,
            parameters=Parameters(
                type="object",
                properties={
                    "path": {"type": "string", "description": "目录路径"},
                    "show_hidden": {"type": "boolean", "description": "显示隐藏文件"}
                },
                required=[]
            )
        )


# ==================== 工具工厂 ====================

def create_all_tools(
    mode_manager: Optional[AgentModeManager] = None,
    session_id: Optional[str] = None,
    model_provider: str = "openai",
    api_key: Optional[str] = None,
    api_base: Optional[str] = None,
    model_name: str = "gpt-4o",
    subtask_event_callback=None,
    ws_manager=None
) -> List[AgentTool]:
    """创建所有工具实例

    Args:
        mode_manager: 模式管理器（可选）
        session_id: 会话 ID（可选，用于 TodoWrite 和浏览器工具）
        model_provider: 模型提供商（用于 Task 子代理）
        api_key: API 密钥（用于 Task 子代理）
        api_base: API Base URL（用于 Task 子代理）
        model_name: 模型名称（用于 Task 子代理）
        subtask_event_callback: 子任务事件回调（用于 Task 工具）
        ws_manager: WebSocket 管理器（可选，用于 ask_user_question 工具）

    Returns:
        工具列表
    """
    # 导入 TodoWriteTool 和 TodoModifyTool
    from .todo_tools import create_todo_tool, create_todo_modify_tool
    # 导入浏览器工具
    from .browser_tools import create_browser_tools
    from .browser_use_tools import create_browser_use_tools
    # 导入邮件工具
    from .email_tool import create_email_tool
    # 导入 Plan 模式工具
    from .plan_tools import create_plan_tools
    # 导入 Web 工具
    from .web_tools import create_web_fetch_tool
    # 导入用户交互工具
    from .user_interaction_tools import create_ask_user_question_tool
    # 导入 Task 子代理工具
    from .task_tools import create_task_tool
    # 导入 GitCode 工具
    from .gitcode_tools import create_gitcode_tools
    # 导入 WebSearch 工具
    from .web_search_tools import create_web_search_tool
    # 导入 Skill 工具
    from .skill_tools import create_skill_use_tool
    # 导入腾讯文档专用工具（快速版，不用 AI 驱动）
    from .tencent_docs_tool import create_tencent_docs_tools

    tools = [
        ReadFileTool(mode_manager),
        WriteFileTool(mode_manager),
        EditFileTool(mode_manager),
        BashTool(mode_manager),
        GrepTool(mode_manager),
        GlobTool(mode_manager),
        ListDirTool(mode_manager),
        create_todo_tool(mode_manager, session_id),
        create_todo_modify_tool(mode_manager, session_id),  # TodoModify 工具
        create_web_fetch_tool(mode_manager),  # WebFetch 工具
        create_web_search_tool(mode_manager),  # WebSearch 工具
        create_ask_user_question_tool(
            mode_manager, ws_manager, session_id
        ),  # AskUserQuestion 工具
        create_task_tool(
            mode_manager=mode_manager,
            session_id=session_id,
            model_provider=model_provider,
            api_key=api_key,
            api_base=api_base,
            model_name=model_name,
            subtask_event_callback=subtask_event_callback
        ),  # Task 子代理工具
        create_skill_use_tool(mode_manager),  # Skill 使用工具
    ]

    # 添加浏览器工具 (agent-browser) - 已禁用，改用 browser-use
    # tools.extend(create_browser_tools(mode_manager, session_id))

    # 添加 browser-use 工具 (AI驱动，可视化弹窗，实时进度更新)
    tools.extend(create_browser_use_tools(
        mode_manager=mode_manager,
        session_id=session_id,
        headless=False,
        window_width=800,
        window_height=600,
        subtask_event_callback=subtask_event_callback,
        ws_manager=ws_manager
    ))

    # 添加邮件工具
    tools.append(create_email_tool(mode_manager, session_id))

    # 添加 Plan 模式工具
    tools.extend(create_plan_tools(mode_manager, session_id))

    # 添加 GitCode 工具
    tools.extend(create_gitcode_tools(mode_manager))

    # 添加腾讯文档专用工具（快速版，直接 Playwright 脚本）
    tools.extend(create_tencent_docs_tools(mode_manager, headless=False))

    # 批量包装为新 AgentTool 接口
    return [wrap_legacy_tool(t) for t in tools]


def create_tools_for_mode(
    mode_manager: AgentModeManager,
    session_id: Optional[str] = None,
    model_provider: str = "openai",
    api_key: Optional[str] = None,
    api_base: Optional[str] = None,
    model_name: str = "gpt-4o",
    subtask_event_callback=None,
    ws_manager=None
) -> List[AgentTool]:
    """根据模式创建可用的工具

    Args:
        mode_manager: 模式管理器
        session_id: 会话 ID（可选）
        model_provider: 模型提供商（用于 Task 子代理）
        api_key: API 密钥（用于 Task 子代理）
        api_base: API Base URL（用于 Task 子代理）
        model_name: 模型名称（用于 Task 子代理）
        subtask_event_callback: 子任务事件回调（用于 Task 工具）
        ws_manager: WebSocket 管理器（可选，用于 ask_user_question 工具）

    Returns:
        当前模式下可用的工具列表
    """
    all_tools = create_all_tools(
        mode_manager=mode_manager,
        session_id=session_id,
        model_provider=model_provider,
        api_key=api_key,
        api_base=api_base,
        model_name=model_name,
        subtask_event_callback=subtask_event_callback,
        ws_manager=ws_manager
    )

    # 根据模式过滤工具
    mode = mode_manager.get_current_mode()

    if mode == AgentMode.BUILD:
        # BUILD 模式：所有工具可用
        return all_tools
    elif mode == AgentMode.PLAN:
        # PLAN 模式：只读工具 + TodoWrite/Modify + 只读浏览器工具 + Plan 工具 + WebFetch + AskUserQuestion + Task(受限) + SkillUse
        plan_mode_tools = [
            "read_file", "grep", "glob", "ls", "bash",
            "todo_write", "todo_modify",  # Todo 工具
            "browser_open", "browser_snapshot", "browser_screenshot",
            "browser_scroll", "browser_wait",
            "enter_plan_mode", "exit_plan_mode",  # Plan 工具
            "web_fetch",  # Web 工具
            "ask_user_question",  # 用户交互工具
            "task",  # Task 子代理工具（在 PLAN 模式下只能使用 Explore/Plan 子代理）
            "skill_use"  # Skill 使用工具
        ]
        return [t for t in all_tools if t.name in plan_mode_tools]
    elif mode == AgentMode.REVIEW:
        # REVIEW 模式：只读工具 + TodoWrite/Modify + 只读浏览器工具 + Task(受限) + bash(用于 gh 等只读命令) + SkillUse
        read_only_tools = [
            "read_file", "grep", "glob", "ls", "bash",
            "todo_write", "todo_modify",  # Todo 工具
            "browser_snapshot", "browser_screenshot",
            "task",  # Task 子代理工具（在 REVIEW 模式下可使用 Explore/Bash 子代理）
            "skill_use"  # Skill 使用工具
        ]
        return [t for t in all_tools if t.name in read_only_tools]

    return all_tools

