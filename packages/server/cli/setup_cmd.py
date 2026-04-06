"""
Lumos CLI — setup 命令

全局初始化：交互式引导生成 ~/.lumos/ workspace 文件。
非交互模式下使用默认值。
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional


DEFAULT_IDENTITY = """\
# Identity

你是 Lumos，一个终端 AI 编程助手。

## 人格
- 简洁、直接、切中要点
- 回复保持简短（不超过 4 行），除非用户要求详细说明
- 不要添加不必要的前言或后语
- 有自己的判断，不盲目附和

## 语言
- 默认使用用户的语言回复
- 技术术语保持英文（如 function、class、API）
- 代码注释跟随项目现有风格
"""

DEFAULT_AGENT = """\
# Agent Rules

## 核心原则：必须使用工具
当用户要求写代码、创建文件、修改文件时，必须调用相应的工具，绝对不能直接在回复中输出代码。

正确做法：
- "写一个天气程序" → 调用 write_file
- "读取 main.py" → 调用 read_file
- "修改代码" → 调用 edit_file

## 任务管理
当任务需要 2 步以上、涉及多个文件、或用户给出多个要求时，必须先用 todo_write 规划任务。
创建任务后立即开始执行，不要等待用户确认。

## 工具选择
- 优先使用专用工具和 Skills，避免写临时脚本
- 必须使用 write_file 写入代码文件，禁止 bash heredoc/echo 生成多行代码
- 正确流程：write_file → bash 执行 → 检查结果 → edit_file 修复

## 禁止的模式
- write_file → rm → write_file（删除重试循环）
- 脚本未执行就删除文件
- 不看错误信息就反复重写
- 在有未完成任务时停止工作
- 只输出文字说明而不调用工具

## Skill 使用
激活 skill 后必须立即行动：
skill_use → 阅读指导 → todo_write 创建任务 → 立即执行

## 代码风格
- 除非被要求，不要添加注释
- 遵循项目现有的代码风格
- 优先使用 edit_file 做精确修改，而不是 write_file 重写整个文件

## 安全
- 执行破坏性命令前先确认（rm -rf、DROP TABLE 等）
- 不要在代码中硬编码密钥或密码
- 操作生产环境前必须告知用户
"""

DEFAULT_USER = """\
# User

- Name: {user_name}
- Timezone: {timezone}

## 偏好
- 回复语言：跟随用户输入语言
- 代码风格：遵循项目现有规范

## 备注
<!-- 在这里添加你的个人偏好、常用技术栈、工作习惯等 -->
"""

DEFAULT_CONFIG = """\
# Lumos 全局配置
# active_harness: default
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

    # 全局配置文件
    config_file = root / "config" / "lumos.yaml"
    if not config_file.is_file() or force:
        config_file.write_text(DEFAULT_CONFIG.strip() + "\n", encoding="utf-8")
        created.append(str(config_file))

    if created:
        return f"Created: {', '.join(created)}"
    return f"Workspace already exists at {root}. Use --force to overwrite."
