"""
Lumos Interceptor Builtin — Write-Rm 循环检测器

从 LumosAgent._detect_write_rm_loop() 迁移而来。
检测 write_file → bash(rm) 的反模式，注入警告到工具结果。
"""

from __future__ import annotations

from typing import Optional

from ..base import BaseInterceptor
from ..types import ToolRequest, ToolResult


WARNING_MESSAGE = (
    "\n\n<system_reminder>\n"
    "⚠️ 检测到 write_file → rm 循环模式！\n\n"
    "这通常表示写入的文件有问题。请不要继续删除重试。\n\n"
    "正确做法：\n"
    "1. 使用 read_file 检查写入的文件内容是否正确\n"
    "2. 如果是 Python 脚本，用 bash 执行查看错误信息\n"
    "3. 根据错误信息修复代码（使用 edit_file）\n"
    "4. 如果写入只有 1 行但应该有多行，可能是换行符格式问题\n\n"
    "停止删除文件，改为诊断和修复问题。\n"
    "</system_reminder>\n"
)


class WriteRmLoopDetector(BaseInterceptor):
    """检测 write_file → bash(rm) 循环反模式

    在 post_tool_use 中记录工具调用历史，检测到循环时
    将警告注入到工具结果末尾。只警告一次。
    """

    name = "write-rm-loop-detector"
    priority = 80

    def __init__(self, threshold: int = 2, history_max: int = 50):
        self._history: list[dict] = []
        self._threshold = threshold
        self._history_max = history_max
        self._warned = False

    def reset(self) -> None:
        """重置状态（新对话时调用）"""
        self._history.clear()
        self._warned = False

    def _detect(self) -> Optional[str]:
        """检测 write-rm 循环，返回警告消息或 None"""
        if len(self._history) < 4:
            return None

        recent = self._history[-10:]
        write_rm_count = 0
        written_files: set[str] = set()

        for call in recent:
            tool_name = call.get("tool_name", "")
            args = call.get("arguments", {})

            if tool_name == "write_file":
                file_path = args.get("file_path", "")
                if file_path:
                    written_files.add(file_path)
            elif tool_name == "bash":
                command = args.get("command", "")
                if "rm " in command or "rm\n" in command:
                    for wf in written_files:
                        if wf in command:
                            write_rm_count += 1

        if write_rm_count >= self._threshold:
            return WARNING_MESSAGE
        return None

    async def post_tool_use(self, result: ToolResult, proceed):
        # 记录历史
        self._history.append({
            "tool_name": result.tool_name,
            "arguments": (result.request.arguments if result.request else {}),
        })
        if len(self._history) > self._history_max:
            self._history = self._history[-30:]

        # 检测循环
        if not self._warned:
            warning = self._detect()
            if warning:
                self._warned = True
                from ...core.types import TextContent
                result.content = list(result.content) + [TextContent(text=warning)]

        return await proceed(result)
