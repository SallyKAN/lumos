"""
Skill 匹配器

根据用户输入匹配合适的 skill。
"""

import re
from typing import List, Optional, Tuple

from .models import Skill
from .loader import SkillLoader


class SkillMatcher:
    """Skill 匹配器

    支持两种匹配方式：
    1. 显式调用：/skill <skill-name> 或 /<skill-name>
    2. 声明式匹配：根据 description 自动匹配（基于关键词）
    """

    def __init__(self, loader: SkillLoader):
        """初始化匹配器

        Args:
            loader: Skill 加载器
        """
        self.loader = loader

    def match_explicit(self, user_input: str) -> Optional[Tuple[Skill, str]]:
        """显式匹配 skill

        支持格式：
        - /skill <skill-name> [args]
        - /<skill-name> [args]

        Args:
            user_input: 用户输入

        Returns:
            (Skill, 剩余参数) 或 None
        """
        user_input = user_input.strip()

        # 匹配 /skill <name> [args]
        skill_cmd_pattern = r'^/skill\s+(\S+)(?:\s+(.*))?$'
        match = re.match(skill_cmd_pattern, user_input, re.IGNORECASE)
        if match:
            skill_name = match.group(1)
            args = match.group(2) or ""
            skill = self.loader.get_skill(skill_name)
            if skill:
                return (skill, args.strip())

        # 匹配 /<skill-name> [args]（直接使用 skill 名称作为命令）
        if user_input.startswith('/'):
            parts = user_input[1:].split(maxsplit=1)
            if parts:
                skill_name = parts[0]
                args = parts[1] if len(parts) > 1 else ""
                skill = self.loader.get_skill(skill_name)
                if skill:
                    return (skill, args.strip())

        return None

    def match_declarative(self, user_input: str) -> Optional[Skill]:
        """声明式匹配 skill

        根据 skill 的 description 进行关键词匹配

        Args:
            user_input: 用户输入

        Returns:
            最佳匹配的 Skill 或 None
        """
        user_input_lower = user_input.lower()
        skills = self.loader.list_skills()

        best_match: Optional[Skill] = None
        best_score = 0

        for skill in skills:
            score = self._calculate_match_score(user_input_lower, skill)
            if score > best_score:
                best_score = score
                best_match = skill

        # 只有当匹配分数超过阈值时才返回
        if best_score >= 2:  # 至少匹配 2 个关键词
            return best_match

        return None

    def _calculate_match_score(self, user_input: str, skill: Skill) -> int:
        """计算匹配分数

        基于 description 中的关键词匹配

        Args:
            user_input: 用户输入（已转小写）
            skill: Skill 对象

        Returns:
            匹配分数
        """
        description = skill.description.lower()

        # 提取 description 中的关键词
        # 移除常见停用词
        stop_words = {
            'use', 'when', 'the', 'a', 'an', 'is', 'are', 'to', 'for',
            'and', 'or', 'with', 'this', 'that', 'from', 'by', 'on',
            'in', 'of', 'as', 'at', 'be', 'it', 'you', 'your'
        }
        words = re.findall(r'\b\w+\b', description)
        keywords = [w for w in words if w not in stop_words and len(w) > 2]

        # 计算匹配的关键词数量
        score = 0
        for keyword in keywords:
            if keyword in user_input:
                score += 1

        # 如果 skill 名称出现在输入中，额外加分
        if skill.name.lower() in user_input:
            score += 3

        return score

    def match(self, user_input: str) -> Optional[Tuple[Skill, str]]:
        """匹配 skill（综合显式和声明式）

        优先显式匹配，其次声明式匹配

        Args:
            user_input: 用户输入

        Returns:
            (Skill, 参数) 或 None
        """
        # 1. 尝试显式匹配
        result = self.match_explicit(user_input)
        if result:
            return result

        # 2. 尝试声明式匹配
        skill = self.match_declarative(user_input)
        if skill:
            return (skill, user_input)

        return None

    def list_matching_skills(
        self,
        user_input: str,
        min_score: int = 1
    ) -> List[Tuple[Skill, int]]:
        """列出所有匹配的 skills 及其分数

        Args:
            user_input: 用户输入
            min_score: 最小匹配分数

        Returns:
            (Skill, 分数) 列表，按分数降序排列
        """
        user_input_lower = user_input.lower()
        skills = self.loader.list_skills()

        matches = []
        for skill in skills:
            score = self._calculate_match_score(user_input_lower, skill)
            if score >= min_score:
                matches.append((skill, score))

        # 按分数降序排列
        matches.sort(key=lambda x: x[1], reverse=True)
        return matches
