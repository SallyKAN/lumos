"""
Skill 使用工具

让 LLM 能够主动选择和激活 skill。
"""

import os
import asyncio
from typing import Optional


from ..core.tool import Tool, ToolInfo, Parameters, Param

from ..agents.mode_manager import AgentModeManager


class SkillUseTool(Tool):
    """Skill 使用工具

    让 LLM 可以主动选择和激活一个 skill 来处理特定任务。
    激活后，skill 的详细指导将被返回给 LLM。
    """

    def __init__(
        self,
        mode_manager: Optional[AgentModeManager] = None,
        skill_manager=None
    ):
        super().__init__()
        self.mode_manager = mode_manager
        self._skill_manager = skill_manager
        self.name = "skill_use"
        self.description = """激活一个 skill 来处理特定任务。

使用说明:
- 当用户请求与某个 skill 的描述匹配时，使用此工具激活该 skill
- 激活后会返回 skill 的详细指导，请按照指导完成任务
- 一次只能激活一个 skill

参数:
- skill_name: 要激活的 skill 名称（必需）
"""
        self.params = [
            Param(
                name="skill_name",
                description="要激活的 skill 名称",
                param_type="string",
                required=True
            ),
        ]

    @property
    def skill_manager(self):
        """延迟获取 SkillManager 实例"""
        if self._skill_manager is None:
            from ..skills.manager import SkillManager
            self._skill_manager = SkillManager()
            self._skill_manager.load_skills()
        return self._skill_manager

    def invoke(self, inputs: dict, **kwargs) -> str:
        """同步调用"""
        return asyncio.run(self.ainvoke(inputs, **kwargs))

    async def ainvoke(self, inputs: dict, **kwargs) -> str:
        """异步调用"""
        # 支持多种参数名变体
        skill_name = (
            inputs.get("skill_name")
            or inputs.get("name")
            or inputs.get("skill")
            or ""
        )

        if isinstance(skill_name, str):
            skill_name = skill_name.strip()

        if not skill_name:
            # 提供详细的错误信息和可用 skills 列表
            available_skills = self.skill_manager.list_skills()
            skill_list = ", ".join([s.name for s in available_skills]) if available_skills else "无"

            return f"""错误: 未指定 skill 名称

请使用以下格式调用 skill_use 工具:
{{
  "skill_name": "skill-creator"
}}

可用的 skills: {skill_list}

收到的参数: {inputs}"""

        # 获取 skill
        skill = self.skill_manager.get_skill(skill_name)

        if not skill:
            # 列出可用的 skills
            available_skills = self.skill_manager.list_skills()
            if available_skills:
                skill_names = [s.name for s in available_skills]
                return (
                    f"错误: 未找到名为 '{skill_name}' 的 skill。\n\n"
                    f"可用的 skills: {', '.join(skill_names)}"
                )
            else:
                return f"错误: 未找到名为 '{skill_name}' 的 skill，且没有可用的 skills。"

        # 激活 skill
        self.skill_manager.activate_skill(skill)

        # 返回 skill 的详细内容
        result_parts = [
            f"✅ 已激活 Skill: {skill.name}",
            "",
            "=" * 50,
            f"## Skill 指导",
            "",
            skill.content,
            "",
            "=" * 50,
        ]

        # 添加工具限制提醒
        if skill.allowed_tools:
            tools_str = ', '.join(sorted(skill.allowed_tools))
            result_parts.extend([
                "",
                f"⚠️ **工具限制**: 此 skill 只允许使用以下工具: {tools_str}",
            ])

        result_parts.extend([
            "",
            "=" * 50,
            "",
            "⚡ **立即执行**: 你必须现在就开始执行任务，不要等待用户确认！",
            "",
            "下一步行动：",
            "1. 根据 skill 指导，使用 todo_write 创建任务清单",
            "2. 立即开始执行第一个任务",
            "3. 不要停下来询问用户，直接动手做！",
        ])

        return "\n".join(result_parts)

    def get_tool_info(self) -> ToolInfo:
        """获取工具信息"""
        return ToolInfo(
            type="function",
            name=self.name,
            description=self.description,
            parameters=Parameters(
                type="object",
                properties={
                    "skill_name": {
                        "type": "string",
                        "description": "要激活的 skill 名称"
                    }
                },
                required=["skill_name"]
            )
        )


def create_skill_use_tool(
    mode_manager: Optional[AgentModeManager] = None,
    skill_manager=None
) -> Tool:
    """创建 SkillUse 工具实例

    Args:
        mode_manager: 模式管理器（可选）
        skill_manager: Skill 管理器（可选，延迟初始化）

    Returns:
        SkillUseTool 实例
    """
    return SkillUseTool(mode_manager, skill_manager)
