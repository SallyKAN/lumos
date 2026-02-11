"""
Skill 执行器

负责执行 skill 并管理工具权限。
"""

from typing import List, Optional, Set

from .models import Skill


# 工具名称映射（支持大小写不敏感和别名）
TOOL_NAME_MAP = {
    # Claude Code 风格 -> lumos 内部名称
    'bash': 'bash',
    'read': 'read_file',
    'read_file': 'read_file',
    'readfile': 'read_file',
    'write': 'write_file',
    'write_file': 'write_file',
    'writefile': 'write_file',
    'edit': 'edit_file',
    'edit_file': 'edit_file',
    'editfile': 'edit_file',
    'grep': 'grep',
    'glob': 'glob',
    'ls': 'ls',
    'todowrite': 'todowrite',
    'todo_write': 'todowrite',
    'task': 'task',
    'websearch': 'websearch',
    'web_search': 'websearch',
    'webfetch': 'webfetch',
    'web_fetch': 'webfetch',
    'askuserquestion': 'askuserquestion',
    'ask_user_question': 'askuserquestion',
}


class SkillExecutionContext:
    """Skill 执行上下文

    管理 skill 执行期间的状态和权限
    """

    def __init__(self, skill: Skill):
        """初始化执行上下文

        Args:
            skill: 要执行的 Skill
        """
        self.skill = skill

    @property
    def allowed_tools(self) -> Set[str]:
        """获取允许的工具集（已规范化）"""
        normalized = set()
        for tool in self.skill.allowed_tools:
            tool_lower = tool.lower()
            normalized_name = TOOL_NAME_MAP.get(tool_lower, tool_lower)
            normalized.add(normalized_name)
        return normalized

    def get_prompt_injection(self) -> str:
        """获取要注入到系统提示词的内容"""
        return self.skill.to_prompt_injection()

    def is_tool_allowed(self, tool_name: str) -> bool:
        """检查工具是否被允许

        Args:
            tool_name: 工具名称

        Returns:
            如果允许返回 True，否则返回 False
        """
        # 如果没有指定 allowed-tools，允许所有工具
        if not self.skill.allowed_tools:
            return True

        # 规范化工具名称
        tool_lower = tool_name.lower()
        normalized_name = TOOL_NAME_MAP.get(tool_lower, tool_lower)

        return normalized_name in self.allowed_tools


class SkillExecutor:
    """Skill 执行器

    负责执行 skill 并管理执行上下文
    """

    def __init__(self):
        """初始化执行器"""
        self._current_context: Optional[SkillExecutionContext] = None

    @property
    def is_skill_active(self) -> bool:
        """是否有 skill 正在执行"""
        return self._current_context is not None

    @property
    def current_skill(self) -> Optional[Skill]:
        """当前执行的 skill"""
        return self._current_context.skill if self._current_context else None

    @property
    def current_context(self) -> Optional[SkillExecutionContext]:
        """当前执行上下文"""
        return self._current_context

    def activate_skill(self, skill: Skill) -> SkillExecutionContext:
        """激活 skill

        Args:
            skill: 要激活的 Skill

        Returns:
            执行上下文
        """
        self._current_context = SkillExecutionContext(skill=skill)
        return self._current_context

    def deactivate_skill(self):
        """停用当前 skill"""
        self._current_context = None

    def is_tool_allowed(self, tool_name: str) -> bool:
        """检查工具是否被当前 skill 允许

        Args:
            tool_name: 工具名称

        Returns:
            如果允许返回 True，否则返回 False
        """
        if not self._current_context:
            return True  # 没有激活的 skill，允许所有工具

        return self._current_context.is_tool_allowed(tool_name)

    def filter_tools(self, tools: List) -> List:
        """根据当前 skill 的 allowed-tools 过滤工具

        Args:
            tools: 所有可用工具列表

        Returns:
            过滤后的工具列表
        """
        if not self._current_context:
            return tools  # 没有激活的 skill，返回所有工具

        # 如果 skill 没有指定 allowed-tools，返回所有工具
        if not self._current_context.skill.allowed_tools:
            return tools

        # 过滤工具
        filtered = []
        for tool in tools:
            tool_name = getattr(tool, 'name', str(tool))
            if self._current_context.is_tool_allowed(tool_name):
                filtered.append(tool)

        return filtered

    def get_prompt_suffix(self) -> str:
        """获取要追加到系统提示词的内容

        Returns:
            提示词后缀
        """
        if self._current_context:
            return self._current_context.get_prompt_injection()
        return ""
