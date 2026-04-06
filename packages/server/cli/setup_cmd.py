"""
Lumos CLI — setup 命令

全局初始化：交互式引导生成 ~/.lumos/ workspace 文件。
非交互模式下使用默认值。

Workspace 结构（参考 OpenClaw）：
~/.lumos/
├── IDENTITY.md          # L1: Agent 身份/人格
├── AGENT.md             # L2: 行为规范 + 记忆策略 + 安全规则
├── USER.md              # L3: 用户信息与偏好
├── MEMORY.md            # 长期策展记忆（人工维护的精华）
├── TOOLS.md             # 工具/环境本地配置
├── memory/              # 记忆系统
│   ├── learnings.jsonl  # 只追加的反思归档（机器写入）
│   └── active_insights.md  # MemorySynthesizer 合成的活跃洞察
├── packages/            # 已安装的 Harness Packages
└── config/
    └── lumos.yaml       # 全局配置
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

## 连续性
你每次 session 醒来都是全新的。Workspace 文件就是你的记忆：
- 读取 MEMORY.md 获取长期上下文
- 读取 memory/ 下的近期日志获取短期上下文
- 重要的事情写入文件，不要只记在"脑子里"
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

## 记忆管理
- 重要决策、用户偏好、项目上下文 → 写入 MEMORY.md
- 每日工作记录 → 写入 memory/YYYY-MM-DD.md
- 工具配置、环境信息 → 写入 TOOLS.md
- 不要依赖"心理笔记"，文件 > 记忆

## 安全
- 执行破坏性命令前先确认（rm -rf、DROP TABLE 等）
- 不要在代码中硬编码密钥或密码
- 操作生产环境前必须告知用户
- 私密信息不外泄，在群聊中注意隐私边界
"""

DEFAULT_USER = """\
# User

- Name: {user_name}
- Timezone: {timezone}

## 偏好
- 回复语言：跟随用户输入语言
- 代码风格：遵循项目现有规范

## 技术栈
<!-- 在这里添加你常用的语言、框架、工具 -->

## 备注
<!-- 在这里添加你的个人偏好、工作习惯等 -->
"""

DEFAULT_MEMORY = """\
# Long-Term Memory

这是你的长期策展记忆。记录重要的决策、偏好、经验教训。

与 active_insights.md（自动合成）不同，这个文件由你主动维护。
定期回顾 memory/ 下的日志，把值得长期保留的内容提炼到这里。

## 用户偏好
<!-- 用户的习惯、喜好、工作方式 -->

## 项目上下文
<!-- 重要的项目决策、架构选择、技术栈 -->

## 经验教训
<!-- 踩过的坑、学到的东西、需要记住的模式 -->
"""

DEFAULT_TOOLS = """\
# Tools

Skills 定义工具的使用方式。这个文件记录你的本地环境配置。

## 示例

```markdown
### SSH
- home-server → 192.168.1.100, user: admin

### 常用路径
- 项目目录：~/projects/
- 配置目录：~/.config/
```

在这里添加你的环境特定信息：设备名、SSH 地址、API 端点等。
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
        "MEMORY.md": DEFAULT_MEMORY.strip() + "\n",
        "TOOLS.md": DEFAULT_TOOLS.strip() + "\n",
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
