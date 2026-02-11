"""
Skills 系统模块

提供与 Claude Code 兼容的 Skills 支持，包括：
- Skill 数据模型和解析
- Skill 加载和发现
- Skill 匹配和执行
- 工具权限控制
- 远程插件安装
"""

from .models import Skill, SkillMetadata, SkillSource
from .loader import SkillLoader
from .matcher import SkillMatcher
from .executor import SkillExecutor, SkillExecutionContext
from .manager import SkillManager
from .installer import SkillInstaller, InstalledPlugin, MarketplaceInfo, parse_plugin_spec

__all__ = [
    'Skill',
    'SkillMetadata',
    'SkillSource',
    'SkillLoader',
    'SkillMatcher',
    'SkillExecutor',
    'SkillExecutionContext',
    'SkillManager',
    'SkillInstaller',
    'InstalledPlugin',
    'MarketplaceInfo',
    'parse_plugin_spec',
]
