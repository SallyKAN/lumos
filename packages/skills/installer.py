"""
Skill 安装器

负责从远程 marketplace 安装、更新、卸载 skills。
"""

import json
import shutil
import subprocess
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple


# 默认已知的 marketplace
# 注意：Claude Code 官方使用 "anthropic-agent-skills" 作为 marketplace 名称
# 参考: https://github.com/anthropics/skills README
DEFAULT_MARKETPLACES = {
    "anthropic-agent-skills": "https://github.com/anthropics/skills.git",
    "anthropics": "https://github.com/anthropics/skills.git",  # 别名，保持兼容
}


@dataclass
class MarketplaceInfo:
    """Marketplace 信息"""
    name: str
    url: str
    install_location: Path
    last_updated: Optional[datetime] = None

    def to_dict(self) -> dict:
        return {
            "url": self.url,
            "install_location": str(self.install_location),
            "last_updated": self.last_updated.isoformat() if self.last_updated else None,
        }

    @classmethod
    def from_dict(cls, name: str, data: dict) -> "MarketplaceInfo":
        return cls(
            name=name,
            url=data["url"],
            install_location=Path(data["install_location"]),
            last_updated=datetime.fromisoformat(data["last_updated"]) if data.get("last_updated") else None,
        )


@dataclass
class InstalledPlugin:
    """已安装插件信息"""
    plugin_name: str
    marketplace: str
    install_path: Path
    version: str
    installed_at: datetime
    git_commit: Optional[str] = None
    skills: List[str] = field(default_factory=list)

    @property
    def spec(self) -> str:
        """返回 plugin@marketplace 格式"""
        return f"{self.plugin_name}@{self.marketplace}"

    def to_dict(self) -> dict:
        return {
            "install_path": str(self.install_path),
            "version": self.version,
            "installed_at": self.installed_at.isoformat(),
            "git_commit": self.git_commit,
            "skills": self.skills,
        }

    @classmethod
    def from_dict(cls, spec: str, data: dict) -> "InstalledPlugin":
        plugin_name, marketplace = parse_plugin_spec(spec)
        return cls(
            plugin_name=plugin_name,
            marketplace=marketplace,
            install_path=Path(data["install_path"]),
            version=data["version"],
            installed_at=datetime.fromisoformat(data["installed_at"]),
            git_commit=data.get("git_commit"),
            skills=data.get("skills", []),
        )


def parse_plugin_spec(spec: str) -> Tuple[str, str]:
    """解析 plugin@marketplace 格式

    Args:
        spec: 插件规格，如 example-skills@anthropics

    Returns:
        (plugin_name, marketplace) 元组

    Raises:
        ValueError: 格式无效
    """
    if '@' not in spec:
        raise ValueError(f"无效格式: {spec}，应为 plugin@marketplace")
    plugin, marketplace = spec.rsplit('@', 1)
    if not plugin or not marketplace:
        raise ValueError(f"无效格式: {spec}，plugin 和 marketplace 都不能为空")
    return plugin, marketplace


class SkillInstaller:
    """Skill 安装器

    负责从远程 marketplace 安装、更新、卸载 skills。

    使用示例：
    >>> installer = SkillInstaller()
    >>> installer.install("example-skills@anthropics")
    >>> installer.list_installed()
    >>> installer.uninstall("example-skills@anthropics")
    """

    def __init__(self, base_dir: Optional[Path] = None):
        """初始化安装器

        Args:
            base_dir: 基础目录，默认为 ~/.lumos
        """
        self.base_dir = base_dir or Path.home() / ".lumos"
        self.plugins_dir = self.base_dir / "plugins"
        self.cache_dir = self.plugins_dir / "cache"
        self.marketplaces_dir = self.plugins_dir / "marketplaces"
        self.installed_plugins_file = self.plugins_dir / "installed_plugins.json"
        self.known_marketplaces_file = self.plugins_dir / "known_marketplaces.json"

        # 确保目录存在
        self._ensure_dirs()

    def _ensure_dirs(self):
        """确保必要的目录存在"""
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.marketplaces_dir.mkdir(parents=True, exist_ok=True)

    def _load_installed_plugins(self) -> Dict[str, InstalledPlugin]:
        """加载已安装插件列表"""
        if not self.installed_plugins_file.exists():
            return {}

        data = json.loads(self.installed_plugins_file.read_text())
        plugins = {}
        for spec, plugin_data in data.get("plugins", {}).items():
            try:
                plugin = InstalledPlugin.from_dict(spec, plugin_data)
                expected_path = (
                    self.cache_dir / plugin.marketplace / plugin.plugin_name
                )
                if plugin.install_path != expected_path:
                    plugin.install_path = expected_path
                plugins[spec] = plugin
            except Exception:
                continue
        return plugins

    def _save_installed_plugins(self, plugins: Dict[str, InstalledPlugin]):
        """保存已安装插件列表"""
        data = {
            "version": 1,
            "plugins": {spec: plugin.to_dict() for spec, plugin in plugins.items()},
        }
        self.installed_plugins_file.write_text(json.dumps(data, indent=2, ensure_ascii=False))

    def _load_known_marketplaces(self) -> Dict[str, MarketplaceInfo]:
        """加载已知 marketplace 列表"""
        marketplaces = {}

        # 加载默认 marketplace
        for name, url in DEFAULT_MARKETPLACES.items():
            marketplaces[name] = MarketplaceInfo(
                name=name,
                url=url,
                install_location=self.marketplaces_dir / name,
            )

        # 加载用户配置的 marketplace
        if self.known_marketplaces_file.exists():
            data = json.loads(self.known_marketplaces_file.read_text())
            for name, mp_data in data.items():
                marketplace = MarketplaceInfo.from_dict(name, mp_data)
                expected_location = self.marketplaces_dir / name
                if marketplace.install_location != expected_location:
                    marketplace.install_location = expected_location
                marketplaces[name] = marketplace

        return marketplaces

    def _save_known_marketplaces(self, marketplaces: Dict[str, MarketplaceInfo]):
        """保存已知 marketplace 列表"""
        # 只保存非默认的 marketplace
        data = {}
        for name, mp in marketplaces.items():
            if name not in DEFAULT_MARKETPLACES:
                data[name] = mp.to_dict()
            elif mp.last_updated:
                # 保存更新时间
                data[name] = mp.to_dict()

        self.known_marketplaces_file.write_text(json.dumps(data, indent=2, ensure_ascii=False))

    def _clone_marketplace(self, marketplace: MarketplaceInfo) -> bool:
        """克隆 marketplace 仓库

        Args:
            marketplace: Marketplace 信息

        Returns:
            是否成功
        """
        if marketplace.install_location.exists():
            return True

        try:
            subprocess.run(
                ["git", "clone", "--depth", "1", marketplace.url, str(marketplace.install_location)],
                check=True,
                capture_output=True,
                text=True,
            )
            return True
        except subprocess.CalledProcessError as e:
            raise RuntimeError(f"克隆 marketplace 失败: {e.stderr}")

    def _update_marketplace(self, marketplace: MarketplaceInfo) -> bool:
        """更新 marketplace 仓库

        Args:
            marketplace: Marketplace 信息

        Returns:
            是否成功
        """
        if not marketplace.install_location.exists():
            return self._clone_marketplace(marketplace)

        try:
            subprocess.run(
                ["git", "-C", str(marketplace.install_location), "pull", "--ff-only"],
                check=True,
                capture_output=True,
                text=True,
            )
            return True
        except subprocess.CalledProcessError as e:
            raise RuntimeError(f"更新 marketplace 失败: {e.stderr}")

    def _get_git_commit(self, path: Path) -> Optional[str]:
        """获取 Git commit hash"""
        try:
            result = subprocess.run(
                ["git", "-C", str(path), "rev-parse", "HEAD"],
                check=True,
                capture_output=True,
                text=True,
            )
            return result.stdout.strip()[:8]
        except subprocess.CalledProcessError:
            return None

    def _find_plugin_in_marketplace(self, marketplace_path: Path, plugin_name: str) -> Optional[Path]:
        """在 marketplace 中查找插件

        支持多种结构：
        1. marketplace.json 定义的插件
        2. skills/<plugin-name>/ 目录
        3. plugins/<plugin-name>/ 目录（claude-plugins-official 结构）
        4. <plugin-name>/ 目录

        Args:
            marketplace_path: Marketplace 路径
            plugin_name: 插件名称

        Returns:
            插件路径或 None
        """
        # 方式1：检查 marketplace.json
        marketplace_json = marketplace_path / ".claude-plugin" / "marketplace.json"
        if marketplace_json.exists():
            try:
                data = json.loads(marketplace_json.read_text())
                for plugin in data.get("plugins", []):
                    if plugin.get("name") == plugin_name:
                        # 返回插件目录
                        plugin_path = marketplace_path / plugin_name
                        if plugin_path.exists():
                            return plugin_path
                        # 也检查 plugins 子目录
                        plugin_path = marketplace_path / "plugins" / plugin_name
                        if plugin_path.exists():
                            return plugin_path
            except json.JSONDecodeError:
                pass

        # 方式2：直接目录结构
        # 检查多种常见目录结构
        for candidate in [
            marketplace_path / "skills" / plugin_name,
            marketplace_path / "plugins" / plugin_name,
            marketplace_path / plugin_name,
        ]:
            if candidate.exists() and candidate.is_dir():
                return candidate

        return None

    def _copy_plugin_skills(self, plugin_path: Path, dest_path: Path) -> List[str]:
        """复制插件的 skills 到缓存目录

        Args:
            plugin_path: 插件源路径
            dest_path: 目标路径

        Returns:
            复制的 skill 名称列表
        """
        skills = []

        # 确保目标目录存在
        dest_path.mkdir(parents=True, exist_ok=True)

        # 查找 skills
        # 结构1: plugin_path/skills/<skill-name>/SKILL.md
        skills_dir = plugin_path / "skills"
        if skills_dir.exists():
            for skill_dir in skills_dir.iterdir():
                if skill_dir.is_dir() and (skill_dir / "SKILL.md").exists():
                    dest_skill_dir = dest_path / skill_dir.name
                    if dest_skill_dir.exists():
                        shutil.rmtree(dest_skill_dir)
                    shutil.copytree(skill_dir, dest_skill_dir)
                    skills.append(skill_dir.name)

        # 结构2: plugin_path/<skill-name>/SKILL.md（每个子目录都是一个 skill）
        if not skills:
            for item in plugin_path.iterdir():
                if item.is_dir() and (item / "SKILL.md").exists():
                    dest_skill_dir = dest_path / item.name
                    if dest_skill_dir.exists():
                        shutil.rmtree(dest_skill_dir)
                    shutil.copytree(item, dest_skill_dir)
                    skills.append(item.name)

        # 结构3: plugin_path/SKILL.md（插件本身就是一个 skill）
        if not skills and (plugin_path / "SKILL.md").exists():
            dest_skill_dir = dest_path / plugin_path.name
            if dest_skill_dir.exists():
                shutil.rmtree(dest_skill_dir)
            shutil.copytree(plugin_path, dest_skill_dir)
            skills.append(plugin_path.name)

        return skills

    def install(self, spec: str, force: bool = False) -> InstalledPlugin:
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
        plugin_name, marketplace_name = parse_plugin_spec(spec)

        # 检查是否已安装
        installed = self._load_installed_plugins()
        if spec in installed and not force:
            raise ValueError(f"插件 {spec} 已安装，使用 force=True 强制重新安装")

        # 获取 marketplace 信息
        marketplaces = self._load_known_marketplaces()
        if marketplace_name not in marketplaces:
            # 尝试推断 GitHub URL
            inferred_url = f"https://github.com/{marketplace_name}/skills.git"
            marketplaces[marketplace_name] = MarketplaceInfo(
                name=marketplace_name,
                url=inferred_url,
                install_location=self.marketplaces_dir / marketplace_name,
            )

        marketplace = marketplaces[marketplace_name]

        # 克隆/更新 marketplace
        self._clone_marketplace(marketplace)
        marketplace.last_updated = datetime.now()
        self._save_known_marketplaces(marketplaces)

        # 查找插件
        plugin_path = self._find_plugin_in_marketplace(marketplace.install_location, plugin_name)
        if not plugin_path:
            raise ValueError(f"在 marketplace {marketplace_name} 中找不到插件 {plugin_name}")

        # 复制 skills 到缓存
        cache_path = self.cache_dir / marketplace_name / plugin_name
        skills = self._copy_plugin_skills(plugin_path, cache_path)

        if not skills:
            raise ValueError(f"插件 {plugin_name} 中没有找到有效的 skills")

        # 获取版本信息
        git_commit = self._get_git_commit(marketplace.install_location)

        # 创建安装记录
        plugin = InstalledPlugin(
            plugin_name=plugin_name,
            marketplace=marketplace_name,
            install_path=cache_path,
            version="latest",
            installed_at=datetime.now(),
            git_commit=git_commit,
            skills=skills,
        )

        # 保存安装记录
        installed[spec] = plugin
        self._save_installed_plugins(installed)

        return plugin

    def uninstall(self, spec: str) -> bool:
        """卸载插件

        Args:
            spec: 插件规格，如 example-skills@anthropics

        Returns:
            是否成功

        Raises:
            ValueError: 插件未安装
        """
        _, marketplace_name = parse_plugin_spec(spec)

        installed = self._load_installed_plugins()
        if spec not in installed:
            raise ValueError(f"插件 {spec} 未安装")

        plugin = installed[spec]

        # 删除缓存目录
        if plugin.install_path.exists():
            shutil.rmtree(plugin.install_path)

        # 清理空的 marketplace 目录
        marketplace_cache = self.cache_dir / marketplace_name
        if marketplace_cache.exists() and not any(marketplace_cache.iterdir()):
            marketplace_cache.rmdir()

        # 更新安装记录
        del installed[spec]
        self._save_installed_plugins(installed)

        return True

    def update(self, spec: str) -> InstalledPlugin:
        """更新插件

        Args:
            spec: 插件规格，如 example-skills@anthropics

        Returns:
            更新后的插件信息

        Raises:
            ValueError: 插件未安装
        """
        _, marketplace_name = parse_plugin_spec(spec)

        installed = self._load_installed_plugins()
        if spec not in installed:
            raise ValueError(f"插件 {spec} 未安装")

        # 获取 marketplace 信息
        marketplaces = self._load_known_marketplaces()
        if marketplace_name not in marketplaces:
            raise ValueError(f"未知的 marketplace: {marketplace_name}")

        marketplace = marketplaces[marketplace_name]

        # 更新 marketplace
        self._update_marketplace(marketplace)
        marketplace.last_updated = datetime.now()
        self._save_known_marketplaces(marketplaces)

        # 重新安装
        return self.install(spec, force=True)

    def list_installed(self) -> List[InstalledPlugin]:
        """列出已安装的插件

        Returns:
            已安装插件列表
        """
        installed = self._load_installed_plugins()
        return list(installed.values())

    def get_installed_skills_dir(self) -> Path:
        """获取已安装 skills 的缓存目录

        Returns:
            缓存目录路径
        """
        return self.cache_dir

    def add_marketplace(self, name: str, url: str) -> MarketplaceInfo:
        """添加自定义 marketplace

        Args:
            name: Marketplace 名称
            url: Git 仓库 URL

        Returns:
            Marketplace 信息
        """
        marketplaces = self._load_known_marketplaces()

        marketplace = MarketplaceInfo(
            name=name,
            url=url,
            install_location=self.marketplaces_dir / name,
        )

        marketplaces[name] = marketplace
        self._save_known_marketplaces(marketplaces)

        return marketplace

    def list_marketplaces(self) -> List[MarketplaceInfo]:
        """列出所有已知的 marketplace

        Returns:
            Marketplace 列表
        """
        marketplaces = self._load_known_marketplaces()
        return list(marketplaces.values())
