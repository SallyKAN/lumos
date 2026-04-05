"""
Lumos CLI — init 命令

扫描项目结构，生成 LUMOS.md 模板。
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from ..capability.project_scanner import ProjectScanner

# 项目指令文件搜索顺序（检测已有文件）
EXISTING_FILES = ["LUMOS.md", "CLAUDE.md", "YOYO.md"]


def run_init(project_root: Optional[Path] = None, force: bool = False) -> str:
    """执行 lumos init

    Returns:
        生成的文件路径或状态消息
    """
    root = project_root or Path.cwd()

    # 检查已有文件
    if not force:
        for name in EXISTING_FILES:
            p = root / name
            if p.is_file():
                return f"Already exists: {p}. Use --force to overwrite."

    # 扫描项目
    scanner = ProjectScanner(root)
    info = scanner.scan()

    # 生成 LUMOS.md
    content = _generate_lumos_md(root.name, info)
    output = root / "LUMOS.md"
    output.write_text(content, encoding="utf-8")

    return f"Created {output}"


def _generate_lumos_md(project_name: str, info) -> str:
    """生成 LUMOS.md 模板"""
    lines = [
        f"# {project_name}",
        "",
        "## 项目概述",
        "",
        f"语言: {info.language}",
    ]

    if info.framework:
        lines.append(f"框架: {info.framework}")
    if info.package_manager:
        lines.append(f"包管理: {info.package_manager}")

    lines.extend(["", "## 常用命令", ""])

    if info.build_cmd:
        lines.append(f"- 构建: `{info.build_cmd}`")
    if info.test_cmd:
        lines.append(f"- 测试: `{info.test_cmd}`")
    if info.lint_cmd:
        lines.append(f"- Lint: `{info.lint_cmd}`")

    lines.extend([
        "",
        "## 架构",
        "",
        "<!-- 描述项目的核心架构、目录结构、关键模块 -->",
        "",
        "## 规范",
        "",
        "<!-- 代码风格、命名约定、PR 流程等 -->",
        "",
    ])

    return "\n".join(lines)
