"""
Lumos Capability — Workspace 文件加载器

加载全局 workspace (~/.lumos/) 和项目级 workspace (<project>/.lumos/ + LUMOS.md)。
支持 CLAUDE.md 兼容回退。
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# 项目指令文件搜索顺序
PROJECT_INSTRUCTION_FILES = ["LUMOS.md", "CLAUDE.md"]

# 全局 workspace 文件
WORKSPACE_FILES = ["AGENT.md", "IDENTITY.md", "USER.md", "TOOLS.md"]


class WorkspaceLoader:
    """Workspace 文件加载器

    搜索优先级：项目级 > 全局级 > None

    用法:
        loader = WorkspaceLoader(
            global_path=Path.home() / ".lumos",
            project_root=Path("/my/project"),
        )
        identity = loader.load_file("IDENTITY.md")
        project_instructions = loader.load_file("LUMOS.md")
    """

    def __init__(
        self,
        global_path: Optional[Path] = None,
        project_root: Optional[Path] = None,
        cwd: Optional[Path] = None,
    ):
        self._global_path = global_path or Path.home() / ".lumos"
        self._project_root = project_root
        self._cwd = cwd or project_root

    def load_file(self, filename: str) -> Optional[str]:
        """加载 workspace 文件

        对于 LUMOS.md / CLAUDE.md：级联搜索（cwd 向上到 project_root）
        对于其他文件：项目级 .lumos/ > 全局 ~/.lumos/
        """
        if filename in PROJECT_INSTRUCTION_FILES:
            return self._load_project_instructions()

        # 项目级 .lumos/<filename>
        if self._project_root:
            p = self._project_root / ".lumos" / filename
            if p.is_file():
                return self._read(p)

        # 全局 ~/.lumos/<filename>
        p = self._global_path / filename
        if p.is_file():
            return self._read(p)

        return None

    def _load_project_instructions(self) -> Optional[str]:
        """级联加载 LUMOS.md / CLAUDE.md

        从 cwd 向上搜索到 project_root，所有找到的合并。
        项目根在前，子目录在后。
        """
        if not self._project_root:
            return None

        found: list[tuple[Path, str]] = []
        search_dir = self._cwd or self._project_root

        while True:
            for name in PROJECT_INSTRUCTION_FILES:
                p = search_dir / name
                if p.is_file():
                    content = self._read(p)
                    if content:
                        found.append((search_dir, content))
                    break  # LUMOS.md 优先，找到就不找 CLAUDE.md

            if search_dir == self._project_root:
                break
            parent = search_dir.parent
            if parent == search_dir:
                break  # 到达文件系统根
            search_dir = parent

        if not found:
            return None

        # 项目根在前，子目录在后
        found.reverse()
        return "\n\n".join(content for _, content in found)

    def _read(self, path: Path) -> Optional[str]:
        """安全读取文件"""
        try:
            return path.read_text(encoding="utf-8")
        except Exception as e:
            logger.warning(f"Failed to read {path}: {e}")
            return None

    def load_memory(self, filename: str = "active_insights.md") -> Optional[str]:
        """加载记忆文件（项目级 + 全局级合并）"""
        parts = []

        if self._project_root:
            p = self._project_root / ".lumos" / "memory" / filename
            if p.is_file():
                content = self._read(p)
                if content:
                    parts.append(content)

        p = self._global_path / "memory" / filename
        if p.is_file():
            content = self._read(p)
            if content:
                parts.append(content)

        return "\n\n".join(parts) if parts else None
