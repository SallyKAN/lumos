"""
Lumos CLI — setup 命令

全局初始化：生成 ~/.lumos/workspace/ 目录及模板文件。
模板内容从代码仓 templates/workspace/ 读取。

Workspace 结构：
~/.lumos/
├── workspace/               # 提示词模板 + 记忆
│   ├── IDENTITY.md          # L1: Agent 身份/人格
│   ├── AGENT.md             # L2: 行为规范 + 记忆策略 + 安全规则
│   ├── USER.md              # L3: 用户信息与偏好
│   ├── MEMORY.md            # 长期策展记忆（人工维护）
│   ├── TOOLS.md             # 工具/环境本地配置
│   ├── HEARTBEAT.md         # 心跳检查清单
│   └── memory/              # 记忆系统
│       ├── learnings.jsonl  # 只追加的反思归档（机器写入）
│       └── active_insights.md  # MemorySynthesizer 合成的活跃洞察
├── packages/                # 已安装的 Harness Packages
└── config/
    └── lumos.yaml           # 全局配置
"""

from __future__ import annotations

import importlib.resources
from pathlib import Path
from typing import Optional

# 模板文件列表
TEMPLATE_FILES = [
    "IDENTITY.md",
    "AGENT.md",
    "USER.md",
    "MEMORY.md",
    "TOOLS.md",
    "HEARTBEAT.md",
]

# USER.md 中的占位符
USER_PLACEHOLDERS = {
    "{{user_name}}": "user_name",
    "{{timezone}}": "timezone",
}

DEFAULT_CONFIG = """\
# Lumos 全局配置
# active_harness: default
"""


def _load_template(name: str) -> str:
    """从 templates/workspace/ 加载模板文件"""
    # 先尝试从包资源加载（pip install 后）
    try:
        ref = importlib.resources.files("templates.workspace").joinpath(name)
        return ref.read_text(encoding="utf-8")
    except Exception:
        pass

    # 回退：从源码目录加载（开发模式）
    # setup_cmd.py 在 packages/server/cli/ 下，模板在 templates/workspace/ 下
    source_root = Path(__file__).resolve().parent.parent.parent.parent
    template_path = source_root / "templates" / "workspace" / name
    if template_path.is_file():
        return template_path.read_text(encoding="utf-8")

    # 最终回退：返回最小默认值
    return f"# {name.replace('.md', '')}\n"


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
    workspace = root / "workspace"

    # 创建目录结构
    workspace.mkdir(parents=True, exist_ok=True)
    (workspace / "memory").mkdir(exist_ok=True)
    (root / "packages").mkdir(exist_ok=True)
    (root / "config").mkdir(exist_ok=True)

    created = []

    # 写入模板文件
    for name in TEMPLATE_FILES:
        p = workspace / name
        if p.is_file() and not force:
            continue

        content = _load_template(name)

        # USER.md 替换占位符
        if name == "USER.md":
            content = content.replace("{{user_name}}", user_name)
            content = content.replace("{{timezone}}", timezone)

        p.write_text(content, encoding="utf-8")
        created.append(str(p))

    # 全局配置文件
    config_file = root / "config" / "lumos.yaml"
    if not config_file.is_file() or force:
        config_file.write_text(DEFAULT_CONFIG.strip() + "\n", encoding="utf-8")
        created.append(str(config_file))

    if created:
        return f"Created: {', '.join(created)}"
    return f"Workspace already exists at {workspace}. Use --force to overwrite."
