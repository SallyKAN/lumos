"""
Shell 执行工具

实现安全的命令执行功能，带有完善的权限控制。
参考：docs/02-详细技术设计.md 第 1.4 节
"""

import asyncio
import os
from typing import Dict, Any, Optional

from .base_tool import BaseTool, ToolInput, ToolOutput
from ..agents.mode_manager import AgentModeManager
from ..utils.platform_compat import (
    get_blacklisted_commands,
    get_restricted_paths,
    is_restricted_path,
)


class BashTool(BaseTool):
    """Bash 命令执行工具

    低层工具 - 执行 Shell 命令
    支持模式感知的权限控制（PLAN/REVIEW 模式下禁止破坏性命令）
    """

    def __init__(self, mode_manager: AgentModeManager):
        super().__init__(mode_manager)
        self.name = "bash"
        self.description = "执行 Shell 命令。这是与系统交互的主要工具。"
        self.required_permission = "execute"
        # 加载平台特定的安全配置
        self._blacklisted_commands = get_blacklisted_commands()
        self._restricted_paths = get_restricted_paths()

    async def _execute(self, inputs: ToolInput, **kwargs) -> ToolOutput:
        """执行 Shell 命令

        Args:
            inputs: 包含 command, description, timeout, working_dir 的输入

        Returns:
            ToolOutput: 命令执行结果
        """
        command = inputs.data.get("command", "")
        description = inputs.data.get("description", "")
        timeout = inputs.data.get("timeout", 120)
        working_dir = inputs.data.get("working_dir")

        # 1. 安全检查（黑名单）
        if self._is_command_blacklisted(command):
            return ToolOutput(
                success=False,
                error=f"命令被安全策略阻止（黑名单命令）"
            )

        # 2. 路径安全检查
        if self._has_dangerous_path(command):
            return ToolOutput(
                success=False,
                error=f"命令涉及受限路径，禁止执行"
            )

        # 3. 模式检查（由基类完成，但可以添加额外警告）
        current_mode = self.mode_manager.get_current_mode().value
        if current_mode in ["plan", "review"]:
            # 在只读模式下给出警告
            if self._is_destructive_command(command):
                return ToolOutput(
                    success=False,
                    error=f"检测到破坏性命令，{current_mode.upper()} 模式下禁止执行"
                )

        # 4. 执行命令
        try:
            result = await self._run_command(
                command,
                timeout=timeout,
                working_dir=working_dir
            )

            return ToolOutput(
                success=result["returncode"] == 0,
                data=result
            )

        except asyncio.TimeoutError:
            return ToolOutput(
                success=False,
                error=f"命令执行超时（超过 {timeout} 秒）"
            )
        except Exception as e:
            return ToolOutput(
                success=False,
                error=f"命令执行失败: {str(e)}"
            )

    async def _run_command(
        self,
        command: str,
        timeout: int,
        working_dir: Optional[str] = None
    ) -> Dict[str, Any]:
        """运行命令的核心逻辑

        Args:
            command: 要执行的命令
            timeout: 超时时间（秒）
            working_dir: 工作目录

        Returns:
            包含返回码、stdout、stderr 的字典
        """
        # 使用绝对路径避免 cd
        if working_dir:
            full_command = f"cd {working_dir} && {command}"
        else:
            full_command = command

        # 创建子进程
        process = await asyncio.create_subprocess_shell(
            full_command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )

        try:
            # 等待命令完成（带超时）
            stdout, stderr = await asyncio.wait_for(
                process.communicate(),
                timeout=timeout
            )

            return {
                "returncode": process.returncode,
                "stdout": stdout.decode('utf-8', errors='replace'),
                "stderr": stderr.decode('utf-8', errors='replace'),
                "command": command
            }

        except asyncio.TimeoutError:
            # 超时，杀死进程
            process.kill()
            await process.wait()
            raise

    def _is_command_blacklisted(self, command: str) -> bool:
        """检查命令是否在黑名单中

        Args:
            command: 要检查的命令

        Returns:
            bool: 如果命令在黑名单中返回 True
        """
        for blacklisted in self._blacklisted_commands:
            if blacklisted in command:
                return True
        return False

    def _has_dangerous_path(self, command: str) -> bool:
        """检查命令是否涉及受限路径

        Args:
            command: 要检查的命令

        Returns:
            bool: 如果涉及受限路径返回 True
        """
        # 使用平台兼容的路径检查
        for word in command.split():
            if is_restricted_path(word):
                return True
        return False

    def _is_destructive_command(self, command: str) -> bool:
        """判断是否为破坏性命令

        用于 PLAN/REVIEW 模式的额外检查

        Args:
            command: 要检查的命令

        Returns:
            bool: 如果是破坏性命令返回 True
        """
        destructive_patterns = [
            "rm -rf",
            "rm -r",
            "del ",
            "delete",
            "format",
            "mkfs",
            ">",
            "git commit",
            "git push"
        ]

        command_lower = command.lower()
        return any(pattern in command_lower for pattern in destructive_patterns)
