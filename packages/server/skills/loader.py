"""
Skill 加载器

负责发现和加载 skills，支持多层级目录结构。
"""

import logging
from pathlib import Path
from typing import Dict, List, Optional

from .models import Skill, SkillSource

logger = logging.getLogger(__name__)


class SkillLoader:
    """Skill 加载器

    负责从多个来源发现和加载 skills：
    1. 本地 skills: ~/.lumos/skills/
    2. 项目 skills: <project>/.lumos/skills/
    3. 已安装 skills: ~/.lumos/plugins/cache/

    优先级（高到低）：
    1. 项目 skills（覆盖同名的本地/已安装 skills）
    2. 本地 skills（覆盖同名的已安装 skills）
    3. 已安装 skills（最低优先级）
    """

    def __init__(self, project_root: Optional[Path] = None):
        """初始化加载器

        Args:
            project_root: 项目根目录（用于加载项目级 skills）
        """
        self.project_root = project_root or Path.cwd()
        self._skills_cache: Dict[str, Skill] = {}
        self._loaded = False

    @property
    def local_skills_dir(self) -> Path:
        """本地 skills 目录"""
        return Path.home() / ".lumos" / "skills"

    @property
    def project_skills_dir(self) -> Path:
        """项目 skills 目录"""
        return self.project_root / ".lumos" / "skills"

    @property
    def installed_skills_dir(self) -> Path:
        """已安装 skills 目录（从 marketplace 安装）"""
        return Path.home() / ".lumos" / "plugins" / "cache"

    def _discover_skills_in_dir(
        self,
        base_dir: Path,
        source: SkillSource
    ) -> List[Skill]:
        """在目录中发现 skills

        Args:
            base_dir: 基础目录
            source: Skill 来源

        Returns:
            发现的 Skill 列表
        """
        skills = []

        if not base_dir.exists():
            return skills

        # 遍历子目录，查找 SKILL.md
        for skill_dir in base_dir.iterdir():
            if not skill_dir.is_dir():
                continue

            skill_file = skill_dir / "SKILL.md"
            if skill_file.exists():
                try:
                    skill = Skill.from_file(skill_file, source)
                    skills.append(skill)
                    logger.debug(f"加载 skill: {skill.name} ({source.value})")
                except Exception as e:
                    logger.warning(f"加载 skill 失败 ({skill_file}): {e}")

        return skills

    def _discover_installed_skills(self) -> List[Skill]:
        """发现已安装的 skills（从 marketplace 安装）

        目录结构：
        ~/.lumos/plugins/cache/<marketplace>/<plugin>/<skill>/SKILL.md

        Returns:
            发现的 Skill 列表
        """
        skills = []

        if not self.installed_skills_dir.exists():
            return skills

        # 遍历 marketplace 目录
        for marketplace_dir in self.installed_skills_dir.iterdir():
            if not marketplace_dir.is_dir():
                continue

            # 遍历 plugin 目录
            for plugin_dir in marketplace_dir.iterdir():
                if not plugin_dir.is_dir():
                    continue

                # 遍历 skill 目录
                for skill_dir in plugin_dir.iterdir():
                    if not skill_dir.is_dir():
                        continue

                    skill_file = skill_dir / "SKILL.md"
                    if skill_file.exists():
                        try:
                            skill = Skill.from_file(skill_file, SkillSource.MARKETPLACE)
                            skills.append(skill)
                            logger.debug(
                                f"加载已安装 skill: {skill.name} "
                                f"({marketplace_dir.name}/{plugin_dir.name})"
                            )
                        except Exception as e:
                            logger.warning(f"加载已安装 skill 失败 ({skill_file}): {e}")

        return skills

    def load_all(self, force_reload: bool = False) -> Dict[str, Skill]:
        """加载所有 skills

        优先级（高到低）：
        1. 项目 skills
        2. 本地 skills
        3. 已安装 skills（从 marketplace 安装）

        Args:
            force_reload: 是否强制重新加载

        Returns:
            skill_name -> Skill 的映射
        """
        if self._loaded and not force_reload:
            return self._skills_cache

        self._skills_cache.clear()

        # 按优先级加载（低优先级先加载，高优先级覆盖）

        # 3. 已安装 skills（最低优先级）
        for skill in self._discover_installed_skills():
            self._skills_cache[skill.name] = skill

        # 2. 本地 skills（覆盖同名的已安装 skills）
        for skill in self._discover_skills_in_dir(
            self.local_skills_dir,
            SkillSource.LOCAL
        ):
            self._skills_cache[skill.name] = skill

        # 1. 项目 skills（最高优先级，覆盖同名的本地/已安装 skills）
        for skill in self._discover_skills_in_dir(
            self.project_skills_dir,
            SkillSource.PROJECT
        ):
            self._skills_cache[skill.name] = skill

        self._loaded = True
        logger.info(f"已加载 {len(self._skills_cache)} 个 skills")
        return self._skills_cache

    def get_skill(self, name: str) -> Optional[Skill]:
        """获取指定名称的 skill

        Args:
            name: Skill 名称

        Returns:
            Skill 对象，如果不存在返回 None
        """
        if not self._loaded:
            self.load_all()
        return self._skills_cache.get(name)

    def list_skills(self) -> List[Skill]:
        """列出所有可用的 skills

        Returns:
            Skill 列表
        """
        if not self._loaded:
            self.load_all()
        return list(self._skills_cache.values())

    def ensure_dirs(self):
        """确保 skills 目录存在"""
        self.local_skills_dir.mkdir(parents=True, exist_ok=True)

    def reload(self) -> Dict[str, Skill]:
        """重新加载所有 skills

        Returns:
            skill_name -> Skill 的映射
        """
        return self.load_all(force_reload=True)
