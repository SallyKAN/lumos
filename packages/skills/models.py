"""
Skill 数据模型

定义 Skill 的数据结构和解析逻辑，与 Claude Code 的 SKILL.md 格式兼容。
"""

import re
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import List, Optional, Set

import yaml


class SkillSource(Enum):
    """Skill 来源"""
    LOCAL = "local"           # ~/.lumos/skills/
    PROJECT = "project"       # <project>/.lumos/skills/
    MARKETPLACE = "marketplace"  # 从远程 marketplace 安装


@dataclass
class SkillMetadata:
    """Skill 元数据（YAML frontmatter）

    对应 SKILL.md 文件的 YAML 头部：
    ---
    name: skill-name
    description: 触发条件和用途描述
    allowed-tools: Tool1,Tool2,Tool3
    ---
    """
    name: str
    description: str
    allowed_tools: Set[str] = field(default_factory=set)
    version: str = "1.0.0"
    author: str = ""
    tags: List[str] = field(default_factory=list)

    @classmethod
    def from_yaml(cls, yaml_str: str) -> 'SkillMetadata':
        """从 YAML 字符串解析元数据

        Args:
            yaml_str: YAML 格式的字符串

        Returns:
            SkillMetadata 实例
        """
        data = yaml.safe_load(yaml_str) or {}

        # 解析 allowed-tools（支持逗号分隔字符串或列表）
        allowed_tools_raw = data.get('allowed-tools', '')
        if isinstance(allowed_tools_raw, str):
            allowed_tools = {
                t.strip().lower()
                for t in allowed_tools_raw.split(',')
                if t.strip()
            }
        elif isinstance(allowed_tools_raw, list):
            allowed_tools = {str(t).strip().lower() for t in allowed_tools_raw}
        else:
            allowed_tools = set()

        return cls(
            name=data.get('name', 'unnamed'),
            description=data.get('description', ''),
            allowed_tools=allowed_tools,
            version=data.get('version', '1.0.0'),
            author=data.get('author', ''),
            tags=data.get('tags', [])
        )


@dataclass
class Skill:
    """Skill 完整定义

    包含元数据和 Markdown 内容
    """
    metadata: SkillMetadata
    content: str                    # Markdown 内容（不含 frontmatter）
    source: SkillSource
    file_path: Path

    @property
    def name(self) -> str:
        """Skill 名称"""
        return self.metadata.name

    @property
    def description(self) -> str:
        """Skill 描述"""
        return self.metadata.description

    @property
    def allowed_tools(self) -> Set[str]:
        """允许的工具集"""
        return self.metadata.allowed_tools

    @classmethod
    def from_file(cls, file_path: Path, source: SkillSource) -> 'Skill':
        """从 SKILL.md 文件加载 Skill

        Args:
            file_path: SKILL.md 文件路径
            source: Skill 来源

        Returns:
            Skill 实例

        Raises:
            FileNotFoundError: 文件不存在
            ValueError: 文件格式错误
        """
        content = file_path.read_text(encoding='utf-8')

        # 解析 YAML frontmatter
        # 格式: ---\n<yaml>\n---\n<markdown>
        frontmatter_pattern = r'^---\s*\n(.*?)\n---\s*\n(.*)$'
        match = re.match(frontmatter_pattern, content, re.DOTALL)

        if match:
            yaml_str = match.group(1)
            markdown_content = match.group(2)
            metadata = SkillMetadata.from_yaml(yaml_str)
        else:
            # 无 frontmatter，使用目录名作为 skill 名称
            metadata = SkillMetadata(
                name=file_path.parent.name,
                description=""
            )
            markdown_content = content

        return cls(
            metadata=metadata,
            content=markdown_content.strip(),
            source=source,
            file_path=file_path
        )

    def to_prompt_injection(self) -> str:
        """生成用于注入到系统提示词的内容

        Returns:
            格式化的提示词字符串
        """
        tools_str = ', '.join(sorted(self.allowed_tools)) if self.allowed_tools else '所有工具'

        return f"""
## 当前激活的 Skill: {self.name}

{self.content}

---
**Skill 约束:**
- 允许的工具: {tools_str}
- 请严格遵循上述 Skill 的指导完成任务
"""

    def __repr__(self) -> str:
        return f"Skill(name={self.name!r}, source={self.source.value})"
