"""
Agent 模式管理器

实现 build/plan/review 三种 Agent 模式的管理。
参考：docs/01-架构设计.md 第 3.1 节
"""

from enum import Enum
from typing import Dict, Set
from dataclasses import dataclass

from ..utils.platform_compat import get_mode_blocked_commands


class AgentMode(Enum):
    """Agent 模式枚举

    三种模式的详细说明：
    - BUILD: 完全开发权限，可以修改文件、执行命令
    - PLAN: 只读模式，用于代码探索和规划
    - REVIEW: 代码审查模式，专注于质量分析
    """
    BUILD = "build"       # 完全权限
    PLAN = "plan"         # 只读模式
    REVIEW = "review"     # 代码审查


@dataclass
class ModePermissions:
    """模式权限配置

    定义每种模式下允许的工具、阻止的命令等
    """
    allowed_tools: Set[str]
    blocked_commands: Set[str]
    read_only: bool
    prompt_suffix: str


class AgentModeManager:
    """Agent 模式管理器

    负责管理 Agent 的模式切换和权限控制。

    使用示例：
    >>> manager = AgentModeManager()
    >>> manager.switch_mode(AgentMode.PLAN)
    >>> manager.is_tool_allowed("write_file")  # False
    >>> manager.is_tool_allowed("read_file")   # True
    """

    def __init__(self, initial_mode: AgentMode = AgentMode.BUILD):
        """初始化模式管理器

        Args:
            initial_mode: 初始模式，默认为 BUILD
        """
        self.current_mode = initial_mode
        self.mode_configs = self._init_mode_configs()

    def _init_mode_configs(self) -> Dict[AgentMode, ModePermissions]:
        """初始化模式配置

        为每种模式定义详细的权限和提示词
        """
        # 获取平台特定的阻止命令
        blocked_commands = get_mode_blocked_commands()

        return {
            AgentMode.BUILD: ModePermissions(
                allowed_tools={
                    "read_file", "write_file", "edit_file",
                    "bash", "grep", "glob", "todowrite", "task"
                },
                blocked_commands=set(),
                read_only=False,
                prompt_suffix=self._get_build_prompt_suffix()
            ),
            AgentMode.PLAN: ModePermissions(
                allowed_tools={
                    "read_file", "grep", "glob",
                    "bash", "websearch", "webfetch", "todowrite"
                },
                blocked_commands=blocked_commands,
                read_only=True,
                prompt_suffix=self._get_plan_prompt_suffix()
            ),
            AgentMode.REVIEW: ModePermissions(
                allowed_tools={
                    "read_file", "grep", "glob",
                    "bash", "lsp_diagnostics", "todowrite"
                },
                blocked_commands=blocked_commands | {"git"},  # REVIEW 模式更严格
                read_only=True,
                prompt_suffix=self._get_review_prompt_suffix()
            )
        }

    def switch_mode(self, new_mode: AgentMode) -> bool:
        """切换模式

        Args:
            new_mode: 要切换到的新模式

        Returns:
            bool: 如果模式发生变化返回 True，否则返回 False
        """
        if new_mode == self.current_mode:
            return False

        self.current_mode = new_mode
        return True

    def get_current_mode(self) -> AgentMode:
        """获取当前模式

        Returns:
            当前的 Agent 模式
        """
        return self.current_mode

    def is_tool_allowed(self, tool_name: str) -> bool:
        """检查工具是否在当前模式下允许

        Args:
            tool_name: 工具名称

        Returns:
            bool: 如果工具允许使用返回 True，否则返回 False
        """
        config = self.mode_configs[self.current_mode]
        return tool_name in config.allowed_tools

    def is_command_blocked(self, command: str) -> bool:
        """检查命令是否在当前模式下被阻止

        Args:
            command: 要执行的命令

        Returns:
            bool: 如果命令被阻止返回 True，否则返回 False
        """
        config = self.mode_configs[self.current_mode]
        for blocked in config.blocked_commands:
            if blocked in command:
                return True
        return False

    def get_mode_prompt_suffix(self) -> str:
        """获取当前模式的提示词后缀

        用于动态注入到系统提示词中

        Returns:
            当前模式特定的提示词后缀
        """
        return self.mode_configs[self.current_mode].prompt_suffix

    def _get_build_prompt_suffix(self) -> str:
        """build 模式提示词"""
        return """
你处于 BUILD 模式。
- 你拥有完全的开发权限
- 可以自由修改文件和执行命令
- 在修改文件前使用 Read 确认内容
- 使用 TodoWrite 跟踪任务进度
"""

    def _get_plan_prompt_suffix(self) -> str:
        """plan 模式提示词"""
        return """
## Plan Mode Active

你处于 PLAN 模式（只读模式）。

### ⚠️ 首要步骤（必须执行）

**在做任何其他事情之前，你必须先调用 `enter_plan_mode` 工具！**

这个工具会：
1. 创建一个 plan 文件用于记录你的方案
2. 返回 plan 文件的路径

只有调用这个工具后，你才能知道应该把方案写入哪个文件。

### 工作流程

#### Phase 1: 初始化
- **立即调用 `enter_plan_mode` 工具**获取 plan 文件路径
- 记住返回的文件路径，后续方案都写入这个文件

#### Phase 2: 理解需求
- 使用 read_file、grep、glob 工具探索代码库
- 理解现有架构和模式
- 识别相关文件和依赖

#### Phase 3: 设计方案
- 设计实现方案
- 考虑多种方案的权衡
- 选择最佳方案

#### Phase 4: 写入计划
- 将最终方案写入 plan 文件（Phase 1 获取的路径）
- 包含: 方案概述、关键文件、实现步骤、验证方法
- 保持简洁但详细

#### Phase 5: 请求审批
- 使用 `exit_plan_mode` 工具请求用户审批
- 在 allowed_prompts 中预申请需要的命令权限

### 限制
- ❌ 不能修改任何文件（plan 文件除外）
- ❌ 不能执行破坏性命令
- ✅ 可以读取文件、搜索代码
- ✅ 可以使用 todo_write 跟踪进度

### 重要：审批等待规则

当你调用 exit_plan_mode 工具后，工具返回中会包含 `<AWAITING_USER_APPROVAL>` 标记。
看到这个标记时，你**必须立即停止**，不要执行任何后续操作：

1. **不要**创建 TodoWrite 任务
2. **不要**调用任何写入工具
3. **不要**开始实现代码
4. **只需要**向用户展示计划摘要，然后等待

只有当用户明确输入 'approve'、'yes' 或类似确认后，你才能切换到 BUILD 模式并开始实现。
"""

    def _get_review_prompt_suffix(self) -> str:
        """review 模式提示词"""
        return """
你处于 REVIEW 模式（代码审查）。
- 专注于代码质量、安全性、性能
- 识别潜在问题和改进机会
- 使用 LSP 诊断信息辅助分析
- 提供建设性的反馈
"""

    def get_mode_info(self) -> Dict[str, any]:
        """获取当前模式的完整信息

        Returns:
            包含当前模式详细信息的字典
        """
        config = self.mode_configs[self.current_mode]
        return {
            "mode": self.current_mode.value,
            "read_only": config.read_only,
            "allowed_tools": list(config.allowed_tools),
            "blocked_commands": list(config.blocked_commands)
        }
