"""
Lumos CLI — setup 命令

全局初始化：交互式引导生成 ~/.lumos/ workspace 文件。
非交互模式下使用默认值。
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional


DEFAULT_IDENTITY = """# Lumos Agent

I am Lumos, a coding assistant.
"""

DEFAULT_AGENT = """# Agent Rules

- Read files before editing
- Run tests after changes
- Ask before destructive operations
- Prefer minimal, focused changes
"""

DEFAULT_USER = """# User

- Name: {user_name}
- Timezone: {timezone}
"""


def run_setup(
    global_path: Optional[Path] = None,
    user_name: str = "User",
    timezone: str = "UTC",
    force: bool = False,
) -> str:
    """执行 lumos setup

    Returns:
        状态消息
    """
    root = global_path or Path.home() / ".lumos"
    root.mkdir(parents=True, exist_ok=True)
    (root / "memory").mkdir(exist_ok=True)
    (root / "packages").mkdir(exist_ok=True)
    (root / "config").mkdir(exist_ok=True)

    created = []

    files = {
        "IDENTITY.md": DEFAULT_IDENTITY.strip() + "\n",
        "AGENT.md": DEFAULT_AGENT.strip() + "\n",
        "USER.md": DEFAULT_USER.format(
            user_name=user_name, timezone=timezone,
        ).strip() + "\n",
    }

    for name, content in files.items():
        p = root / name
        if p.is_file() and not force:
            continue
        p.write_text(content, encoding="utf-8")
        created.append(str(p))

    if created:
        return f"Created: {', '.join(created)}"
    return f"Workspace already exists at {root}. Use --force to overwrite."
