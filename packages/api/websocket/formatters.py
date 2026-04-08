"""
工具消息格式化器

为 Web UI 提供统一的工具消息格式化，优化工具调用和结果的显示。
"""

import re
from typing import Dict, Any, Callable, Optional
from dataclasses import dataclass


@dataclass
class FormattedToolCall:
    """格式化后的工具调用信息"""
    id: str
    name: str
    arguments: Dict[str, Any]
    description: str  # 操作描述，如 "创建 3 个任务"
    formatted_args: str  # 格式化参数摘要


@dataclass
class FormattedToolResult:
    """格式化后的工具结果信息"""
    tool_name: str
    result: str
    success: bool
    tool_call_id: Optional[str]
    summary: str  # 结果摘要


class ToolMessageFormatter:
    """工具消息格式化器

    为所有工具提供统一的格式化接口，生成人性化的描述和摘要。
    """

    def __init__(self):
        # 工具调用格式化器注册表
        self._call_formatters: Dict[str, Callable] = {
            "todo_write": self._format_todo_write_call,
            "read_file": self._format_read_file_call,
            "write_file": self._format_write_file_call,
            "edit_file": self._format_edit_file_call,
            "bash": self._format_bash_call,
            "grep": self._format_grep_call,
            "glob": self._format_glob_call,
            "ls": self._format_ls_call,
        }

        # 工具结果格式化器注册表
        self._result_formatters: Dict[str, Callable] = {
            "todo_write": self._format_todo_write_result,
            "read_file": self._format_read_file_result,
            "write_file": self._format_write_file_result,
            "edit_file": self._format_edit_file_result,
            "bash": self._format_bash_result,
            "grep": self._format_grep_result,
            "glob": self._format_glob_result,
            "ls": self._format_ls_result,
        }

    def format_tool_call(
        self,
        tool_id: str,
        tool_name: str,
        arguments: Dict[str, Any]
    ) -> FormattedToolCall:
        """格式化工具调用

        Args:
            tool_id: 工具调用 ID
            tool_name: 工具名称
            arguments: 工具参数

        Returns:
            FormattedToolCall 对象
        """
        formatter = self._call_formatters.get(
            tool_name,
            self._format_generic_call
        )
        description, formatted_args = formatter(arguments)

        return FormattedToolCall(
            id=tool_id,
            name=tool_name,
            arguments=arguments,
            description=description,
            formatted_args=formatted_args
        )

    def format_tool_result(
        self,
        tool_name: str,
        result: str,
        success: bool,
        tool_call_id: Optional[str] = None
    ) -> FormattedToolResult:
        """格式化工具结果

        Args:
            tool_name: 工具名称
            result: 原始结果
            success: 是否成功
            tool_call_id: 工具调用 ID

        Returns:
            FormattedToolResult 对象
        """
        formatter = self._result_formatters.get(
            tool_name,
            self._format_generic_result
        )
        summary = formatter(result, success)

        return FormattedToolResult(
            tool_name=tool_name,
            result=result,
            success=success,
            tool_call_id=tool_call_id,
            summary=summary
        )

    # ========================================================================
    # 工具调用格式化器
    # ========================================================================

    def _format_generic_call(
        self,
        args: Dict[str, Any]
    ) -> tuple[str, str]:
        """通用工具调用格式化"""
        # 尝试从参数中提取关键信息
        keys = list(args.keys())[:3]
        summary_parts = []
        for key in keys:
            value = args[key]
            if isinstance(value, str) and len(value) > 30:
                value = value[:30] + "..."
            summary_parts.append(f"{key}={value}")

        formatted_args = ", ".join(summary_parts) if summary_parts else ""
        return "执行操作", formatted_args

    def _format_todo_write_call(
        self,
        args: Dict[str, Any]
    ) -> tuple[str, str]:
        """格式化 todo_write 调用"""
        action = args.get("action", "")
        tasks = args.get("tasks", "")
        todos = args.get("todos", [])

        if action == "create":
            if tasks:
                # 统计任务数量
                task_list = [t.strip() for t in re.split(r'[;\n；、]', tasks) if t.strip()]
                task_count = len(task_list)
                description = f"创建 {task_count} 个任务"
                # 只显示第一个任务名作为预览
                if task_list:
                    first_task = self._truncate(task_list[0], 20)
                    if task_count > 1:
                        formatted_args = f"\"{first_task}\" 等"
                    else:
                        formatted_args = f"\"{first_task}\""
                else:
                    formatted_args = ""
            elif todos:
                count = len(todos) if isinstance(todos, list) else 1
                description = f"创建 {count} 个任务"
                formatted_args = ""
            else:
                description = "创建任务列表"
                formatted_args = ""
        elif action == "update":
            task_id = args.get("task_id", args.get("id", ""))
            task_id_short = task_id[:8] if task_id else ""
            status = args.get("status", "")
            description = "更新任务状态"
            formatted_args = f"[{task_id_short}] → {status}" if task_id_short else ""
        elif action == "list":
            description = "查看任务列表"
            formatted_args = ""
        elif action == "clear":
            description = "清除所有任务"
            formatted_args = ""
        else:
            description = f"任务操作"
            formatted_args = action if action else ""

        return description, formatted_args

    def _format_read_file_call(
        self,
        args: Dict[str, Any]
    ) -> tuple[str, str]:
        """格式化 read_file 调用"""
        file_path = args.get("file_path", args.get("path", ""))
        offset = args.get("offset")
        limit = args.get("limit")

        filename = self._get_filename(file_path)
        description = f"读取 {filename}"

        if offset is not None and limit is not None:
            formatted_args = f"第 {offset}-{offset + limit} 行"
        elif offset is not None:
            formatted_args = f"从第 {offset} 行开始"
        elif limit is not None:
            formatted_args = f"前 {limit} 行"
        else:
            formatted_args = "完整文件"

        return description, formatted_args

    def _format_write_file_call(
        self,
        args: Dict[str, Any]
    ) -> tuple[str, str]:
        """格式化 write_file 调用"""
        file_path = args.get("file_path", args.get("path", ""))
        content = args.get("content", "")

        filename = self._get_filename(file_path)
        content_len = len(content) if isinstance(content, str) else 0
        description = f"写入 {filename}"
        formatted_args = f"{content_len} 字符"

        return description, formatted_args

    def _format_edit_file_call(
        self,
        args: Dict[str, Any]
    ) -> tuple[str, str]:
        """格式化 edit_file 调用"""
        file_path = args.get("file_path", args.get("path", ""))
        old_string = args.get("old_string", "")
        new_string = args.get("new_string", "")

        filename = self._get_filename(file_path)
        description = f"编辑 {filename}"

        old_preview = self._truncate(old_string.split('\n')[0], 20)
        formatted_args = f"替换 \"{old_preview}\""

        return description, formatted_args

    def _format_bash_call(
        self,
        args: Dict[str, Any]
    ) -> tuple[str, str]:
        """格式化 bash 调用"""
        command = args.get("command", args.get("cmd", ""))
        description = "执行命令"
        formatted_args = self._truncate(command, 50)

        return description, formatted_args

    def _format_grep_call(
        self,
        args: Dict[str, Any]
    ) -> tuple[str, str]:
        """格式化 grep 调用"""
        pattern = args.get("pattern", args.get("query", ""))
        path = args.get("path", args.get("directory", "."))

        description = f"搜索 \"{self._truncate(pattern, 20)}\""
        formatted_args = f"in {self._get_filename(path)}"

        return description, formatted_args

    def _format_glob_call(
        self,
        args: Dict[str, Any]
    ) -> tuple[str, str]:
        """格式化 glob 调用"""
        pattern = args.get("pattern", args.get("glob_pattern", ""))
        path = args.get("path", args.get("directory", "."))

        description = f"查找文件 \"{pattern}\""
        formatted_args = f"in {self._get_filename(path)}"

        return description, formatted_args

    def _format_ls_call(
        self,
        args: Dict[str, Any]
    ) -> tuple[str, str]:
        """格式化 ls 调用"""
        path = args.get("path", args.get("directory", "."))
        description = "列出目录"
        formatted_args = self._get_filename(path)

        return description, formatted_args

    # ========================================================================
    # 工具结果格式化器
    # ========================================================================

    def _format_generic_result(self, result: str, success: bool) -> str:
        """通用工具结果格式化"""
        if not success:
            # 提取错误摘要
            first_line = result.split('\n')[0] if result else "执行失败"
            return self._truncate(first_line, 50)

        # 成功时返回简短摘要
        lines = result.split('\n') if result else []
        if not lines:
            return "执行完成"

        first_line = lines[0].strip()
        if len(lines) > 1:
            return f"{self._truncate(first_line, 40)} (+{len(lines)-1}行)"
        return self._truncate(first_line, 50)

    def _format_todo_write_result(self, result: str, success: bool) -> str:
        """格式化 todo_write 结果"""
        if not success:
            return self._truncate(result.split('\n')[0], 50)

        # 解析结果中的关键信息
        if "成功创建" in result:
            match = re.search(r'成功创建\s*(\d+)\s*个任务', result)
            if match:
                return f"成功创建 {match.group(1)} 个任务"
        elif "状态更新" in result:
            return "任务状态已更新"
        elif "清除" in result:
            return "已清除所有任务"
        elif "任务列表" in result:
            match = re.search(r'共\s*(\d+)\s*个', result)
            if match:
                return f"共 {match.group(1)} 个任务"

        return self._truncate(result.split('\n')[0], 50)

    def _format_read_file_result(self, result: str, success: bool) -> str:
        """格式化 read_file 结果"""
        if not success:
            return self._truncate(result.split('\n')[0], 50)

        lines = result.split('\n')
        line_count = len(lines)
        return f"读取 {line_count} 行内容"

    def _format_write_file_result(self, result: str, success: bool) -> str:
        """格式化 write_file 结果"""
        if not success:
            return self._truncate(result.split('\n')[0], 50)

        if "成功" in result or "写入" in result:
            return "文件写入成功"
        return self._truncate(result.split('\n')[0], 50)

    def _format_edit_file_result(self, result: str, success: bool) -> str:
        """格式化 edit_file 结果"""
        if not success:
            return self._truncate(result.split('\n')[0], 50)

        if "成功" in result or "替换" in result:
            return "文件编辑成功"
        return self._truncate(result.split('\n')[0], 50)

    def _format_bash_result(self, result: str, success: bool) -> str:
        """格式化 bash 结果"""
        if not success:
            return f"执行失败: {self._truncate(result.split(chr(10))[0], 40)}"

        lines = result.split('\n') if result else []
        line_count = len([l for l in lines if l.strip()])

        if line_count == 0:
            return "执行完成 (无输出)"
        elif line_count == 1:
            return self._truncate(lines[0], 50)
        else:
            return f"执行完成 ({line_count} 行输出)"

    def _format_grep_result(self, result: str, success: bool) -> str:
        """格式化 grep 结果"""
        if not success:
            return self._truncate(result.split('\n')[0], 50)

        lines = result.split('\n') if result else []
        match_count = len([l for l in lines if l.strip()])

        if match_count == 0:
            return "未找到匹配"
        return f"找到 {match_count} 处匹配"

    def _format_glob_result(self, result: str, success: bool) -> str:
        """格式化 glob 结果"""
        if not success:
            return self._truncate(result.split('\n')[0], 50)

        lines = result.split('\n') if result else []
        file_count = len([l for l in lines if l.strip()])

        if file_count == 0:
            return "未找到文件"
        return f"找到 {file_count} 个文件"

    def _format_ls_result(self, result: str, success: bool) -> str:
        """格式化 ls 结果"""
        if not success:
            return self._truncate(result.split('\n')[0], 50)

        lines = result.split('\n') if result else []
        item_count = len([l for l in lines if l.strip()])

        return f"列出 {item_count} 个项目"

    # ========================================================================
    # 辅助方法
    # ========================================================================

    def _truncate(self, text: str, max_len: int) -> str:
        """截断文本"""
        if not text:
            return ""
        text = text.strip()
        if len(text) <= max_len:
            return text
        return text[:max_len - 3] + "..."

    def _get_filename(self, path: str) -> str:
        """从路径中提取文件名"""
        if not path:
            return ""
        # 处理路径分隔符
        parts = path.replace('\\', '/').split('/')
        return parts[-1] if parts else path


# 全局单例
_formatter: Optional[ToolMessageFormatter] = None


def get_tool_formatter() -> ToolMessageFormatter:
    """获取工具消息格式化器单例"""
    global _formatter
    if _formatter is None:
        _formatter = ToolMessageFormatter()
    return _formatter
