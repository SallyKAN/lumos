"""
Skill 管理器

整合 loader、matcher、executor、installer，提供统一的 skill 管理接口。
"""

import os
import shutil
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from ..utils.platform_compat import is_absolute_path
from ..utils.platform_compat import is_restricted_path
from ..utils.platform_compat import normalize_path
from .models import Skill
from .models import SkillSource
from .loader import SkillLoader
from .matcher import SkillMatcher
from .executor import SkillExecutor, SkillExecutionContext
from .installer import SkillInstaller, InstalledPlugin, MarketplaceInfo


class SkillManager:
    """Skill 管理器

    提供统一的 skill 管理接口，整合加载、匹配、执行、安装功能。

    使用示例：
    >>> manager = SkillManager(project_root=Path.cwd())
    >>> manager.load_skills()
    >>> skills = manager.list_skills()
    >>> skill = manager.get_skill("my-skill")
    >>> manager.activate_skill(skill)
    >>> manager.deactivate_skill()
    >>> manager.install_plugin("example-skills@anthropics")
    >>> manager.uninstall_plugin("example-skills@anthropics")
    """

    def __init__(self, project_root: Optional[Path] = None):
        """初始化管理器

        Args:
            project_root: 项目根目录
        """
        # 初始化子组件
        self.loader = SkillLoader(project_root)
        self.matcher = SkillMatcher(self.loader)
        self.executor = SkillExecutor()
        self.installer = SkillInstaller()

    def load_skills(self, force_reload: bool = False) -> Dict[str, Skill]:
        """加载所有 skills

        Args:
            force_reload: 是否强制重新加载

        Returns:
            skill_name -> Skill 的映射
        """
        return self.loader.load_all(force_reload)

    def list_skills(self) -> List[Skill]:
        """列出所有可用的 skills

        Returns:
            Skill 列表
        """
        return self.loader.list_skills()

    def get_skill(self, name: str) -> Optional[Skill]:
        """获取指定名称的 skill

        Args:
            name: Skill 名称

        Returns:
            Skill 对象
        """
        return self.loader.get_skill(name)

    def match_skill(self, user_input: str) -> Optional[Tuple[Skill, str]]:
        """匹配 skill

        Args:
            user_input: 用户输入

        Returns:
            (Skill, 参数) 或 None
        """
        return self.matcher.match(user_input)

    def match_explicit(self, user_input: str) -> Optional[Tuple[Skill, str]]:
        """显式匹配 skill

        Args:
            user_input: 用户输入

        Returns:
            (Skill, 参数) 或 None
        """
        return self.matcher.match_explicit(user_input)

    def activate_skill(self, skill: Skill) -> SkillExecutionContext:
        """激活 skill

        Args:
            skill: 要激活的 Skill

        Returns:
            执行上下文
        """
        return self.executor.activate_skill(skill)

    def deactivate_skill(self):
        """停用当前 skill"""
        self.executor.deactivate_skill()

    @property
    def is_skill_active(self) -> bool:
        """是否有 skill 正在执行"""
        return self.executor.is_skill_active

    @property
    def current_skill(self) -> Optional[Skill]:
        """当前执行的 skill"""
        return self.executor.current_skill

    def is_tool_allowed(self, tool_name: str) -> bool:
        """检查工具是否被当前 skill 允许

        Args:
            tool_name: 工具名称

        Returns:
            如果允许返回 True，否则返回 False
        """
        return self.executor.is_tool_allowed(tool_name)

    def filter_tools(self, tools: List) -> List:
        """根据当前 skill 的 allowed-tools 过滤工具

        Args:
            tools: 所有可用工具列表

        Returns:
            过滤后的工具列表
        """
        return self.executor.filter_tools(tools)

    def get_prompt_suffix(self) -> str:
        """获取 skill 的提示词后缀

        Returns:
            提示词后缀
        """
        return self.executor.get_prompt_suffix()

    def get_skills_prompt(self) -> str:
        """生成可用 skills 的提示词

        用于注入到系统提示词中，让 LLM 知道有哪些 skill 可用。

        Returns:
            格式化的 skill 列表提示词
        """
        skills = self.list_skills()
        if not skills:
            return ""

        lines = [
            "# 可用 Skills",
            "",
            "以下是你可以使用的 Skills。当用户的请求与某个 skill 的描述匹配时，"
            "使用 skill_use 工具激活它：",
            "",
            "| Skill 名称 | 描述 |",
            "|-----------|------|"
        ]

        for skill in skills:
            desc = skill.description[:80] + "..." if len(
                skill.description
            ) > 80 else skill.description
            lines.append(f"| {skill.name} | {desc} |")

        lines.extend([
            "",
            "## 如何使用 Skill",
            "",
            "**重要**: 当用户请求与某个 skill 匹配时，必须先调用 skill_use 工具激活它！",
            "",
            "调用示例（注意：必须传递 skill_name 参数）：",
            "",
            "- 创建 skill: skill_use(skill_name=\"skill-creator\")",
            "- 查询 GitHub 热门项目: skill_use(skill_name=\"github-hot-ai-agents\")",
            "",
            "激活后，skill 的详细指导将被加载，请按照其指导完成任务。"
        ])

        return "\n".join(lines)

    def ensure_dirs(self):
        """确保 skills 目录存在"""
        self.loader.ensure_dirs()

    def reload(self) -> Dict[str, Skill]:
        """重新加载所有 skills

        Returns:
            skill_name -> Skill 的映射
        """
        return self.loader.reload()

    # ==================== 插件安装管理 ====================

    def install_plugin(self, spec: str, force: bool = False) -> InstalledPlugin:
        """安装插件

        Args:
            spec: 插件规格，如 example-skills@anthropics
            force: 是否强制重新安装

        Returns:
            已安装的插件信息

        Raises:
            ValueError: 格式无效或插件不存在
            RuntimeError: 安装失败
        """
        plugin = self.installer.install(spec, force)
        # 重新加载 skills 以包含新安装的
        self.loader.reload()
        return plugin

    def uninstall_plugin(self, spec: str) -> bool:
        """卸载插件

        Args:
            spec: 插件规格，如 example-skills@anthropics

        Returns:
            是否成功

        Raises:
            ValueError: 插件未安装
        """
        result = self.installer.uninstall(spec)
        # 重新加载 skills 以移除已卸载的
        self.loader.reload()
        return result

    def update_plugin(self, spec: str) -> InstalledPlugin:
        """更新插件

        Args:
            spec: 插件规格，如 example-skills@anthropics

        Returns:
            更新后的插件信息

        Raises:
            ValueError: 插件未安装
        """
        plugin = self.installer.update(spec)
        # 重新加载 skills
        self.loader.reload()
        return plugin

    def list_installed_plugins(self) -> List[InstalledPlugin]:
        """列出已安装的插件

        Returns:
            已安装插件列表
        """
        return self.installer.list_installed()

    def import_local_skill(self, path: str, force: bool = False) -> Skill:
        """导入本地 skill。

        Args:
            path: 服务端本地路径（SKILL.md 文件或其目录）
            force: 目标已存在时是否覆盖

        Returns:
            导入后的 Skill

        Raises:
            ValueError: 路径无效或不允许
            FileNotFoundError: 路径或 SKILL.md 不存在
            FileExistsError: 目标已存在且未开启 force
            RuntimeError: 复制失败
        """
        if not path:
            raise ValueError("路径不能为空")

        expanded = os.path.expandvars(os.path.expanduser(path))
        normalized = normalize_path(expanded)

        if not is_absolute_path(normalized):
            raise ValueError("请提供绝对路径")

        if is_restricted_path(normalized):
            raise ValueError("路径位于受限目录")

        raw_path = Path(normalized)
        if not raw_path.exists():
            raise FileNotFoundError("路径不存在")

        for part in [raw_path, *raw_path.parents]:
            if part.is_symlink():
                raise ValueError("不允许使用符号链接路径")

        if raw_path.is_dir():
            skill_file = raw_path / "SKILL.md"
        else:
            if raw_path.name != "SKILL.md":
                raise ValueError("仅支持 SKILL.md 文件路径")
            skill_file = raw_path

        if not skill_file.exists() or not skill_file.is_file():
            raise FileNotFoundError("未找到 SKILL.md")

        skill_dir = skill_file.parent
        self.loader.ensure_dirs()

        dest_dir = self.loader.local_skills_dir / skill_dir.name
        if dest_dir.exists() and not force:
            raise FileExistsError("目标技能已存在")

        try:
            shutil.copytree(skill_dir, dest_dir, dirs_exist_ok=force)
        except Exception as exc:
            raise RuntimeError("复制技能失败") from exc

        skill = Skill.from_file(dest_dir / "SKILL.md", SkillSource.LOCAL)
        self.loader.reload()
        return self.loader.get_skill(skill.name) or skill

    def add_marketplace(self, name: str, url: str) -> MarketplaceInfo:
        """添加自定义 marketplace

        Args:
            name: Marketplace 名称
            url: Git 仓库 URL

        Returns:
            Marketplace 信息
        """
        return self.installer.add_marketplace(name, url)

    def list_marketplaces(self) -> List[MarketplaceInfo]:
        """列出所有已知的 marketplace

        Returns:
            Marketplace 列表
        """
        return self.installer.list_marketplaces()
