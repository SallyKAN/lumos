# Lumos

> 在代码的黑暗中为你照亮方向 — 你的终端 AI 编程助手

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![Platform](https://img.shields.io/badge/platform-Linux%20%7C%20macOS%20%7C%20Windows-lightgrey.svg)](https://github.com/)
[![Tests](https://img.shields.io/badge/tests-19%20passed-brightgreen.svg)](tests/)

## 项目简介

**Lumos** 是一个用自然语言驱动的终端 AI 编程助手，自建 ReAct Agent 核心，无外部 SDK 依赖。像哈利波特的荧光咒一样，在代码的黑暗中为你点亮方向。

```
三大模式，从想法到上线全搞定

BUILD 模式  → 放开手脚写代码，自动化一切
PLAN 模式   → 大任务先出方案，你点头再动手
REVIEW 模式 → 批量审 PR，漏洞 Bug 无处藏
```

### 核心能力

| 能力 | 说明 |
|------|------|
| **自建 ReAct 核心** | 零外部 SDK 依赖，完全自主的 Agent 循环 |
| **Skill 插件系统** | 能力无限扩展，一键安装社区技能 |
| **子Agent并行** | 上下文隔离，多任务同时执行 |
| **浏览器自动化** | 网页操作也能搞定 |
| **双模型路由** | 智能省钱，成本降 70% |
| **跨平台** | Linux / macOS / Windows 通吃 |

## 快速开始

### 安装

```bash
# 1. 克隆项目
git clone https://github.com/SallyKAN/lumos.git
cd lumos

# 2. 创建虚拟环境（需要 Python 3.10+）
python3 -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate

# 3. 安装依赖
pip install --upgrade pip
pip install -e .

# 4. 验证安装
lumos --version
```

### 配置 API Key

```bash
# 方式 1：交互式配置（推荐）
lumos --config

# 方式 2：环境变量
export ANTHROPIC_API_KEY="your-api-key"    # Anthropic Claude
export OPENAI_API_KEY="your-api-key"       # OpenAI

# 方式 3：配置文件（~/.lumos/config.yaml）
cat << EOF > ~/.lumos/config.yaml
provider: "openai"
api_key: "your-api-key"
api_base_url: "https://api.openai.com/v1"
model: "gpt-4o"
EOF
```

### 使用

```bash
# 交互式模式
lumos

# 非交互式
lumos "帮我重构这个函数"
lumos -p "分析项目结构"
```

### 系统要求

- **Python**: 3.10+
- **操作系统**: Linux / macOS / Windows 10+
- **终端**: 支持 ANSI 颜色（Windows 推荐使用 Windows Terminal）

## 核心工具集

| 工具 | 功能 | 说明 |
|------|------|------|
| **ReadFile** | 读取文件 | 支持行号范围、大文件分页 |
| **WriteFile** | 写入文件 | 完全覆盖模式 |
| **EditFile** | 智能编辑 | 字符串替换，保留格式 |
| **Bash** | Shell 执行 | 带安全检查、超时控制 |
| **Grep** | 内容搜索 | 基于 ripgrep，支持正则 |
| **Glob** | 文件匹配 | 支持 `**/*` 递归模式 |
| **LS** | 目录列表 | 列出目录内容 |
| **TodoWrite** | 任务管理 | 持久化任务列表 |
| **WebFetch** | 网页抓取 | 获取网页内容 |
| **WebSearch** | 网络搜索 | 搜索引擎集成 |
| **SpawnSubAgent** | 子Agent | 并行任务，上下文隔离 |
| **EnterPlanMode** | 规划模式 | 复杂任务先规划后执行 |
| **BrowserAutomation** | 浏览器自动化 | 网页交互操作 |

## 内置子Agent

| 子Agent | 用途 | 特点 |
|---------|------|------|
| **Explore** | 代码库探索 | 快速搜索文件、代码关键词、理解项目结构 |
| **Plan** | 方案规划 | 设计实现计划、识别关键文件、权衡架构方案 |
| **Researcher** | 信息调研 | 网络搜索、竞品分析、技术调研 |
| **CodeReviewer** | 代码审查 | 审查代码质量、安全漏洞、最佳实践 |
| **Debugger** | 问题诊断 | 复杂问题诊断、根因分析、系统化排查 |
| **Refactoring** | 代码重构 | 安全代码转换、设计模式应用、结构优化 |

```
┌──────────────────────────────────────────────┐
│              主 Agent (Sonnet)               │
│  - 任务分解与派发                             │
│  - 结果汇总与报告生成                         │
└──────────────┬───────────────────────────────┘
               │ spawn_sub_agents()
    ┌──────────┼──────────┐
    ▼          ▼          ▼
┌────────┐ ┌────────┐ ┌────────┐
│子Agent1│ │子Agent2│ │子Agent3│
│(Haiku) │ │(Haiku) │ │(Haiku) │
│独立上下文│ │独立上下文│ │独立上下文│
└────────┘ └────────┘ └────────┘
```

## 核心用例

### BUILD 模式 - 一句话搞定开发

```
[BUILD] ❯ 帮我修复 src/utils.py 中的类型错误并补充单元测试

● grep("TypeError", src/**/*.py)
  ⎿ 找到 3 处相关代码

● read_file(src/utils.py)
  ⎿ 成功读取 (120 行)

● 思考中...
  发现问题：第 45 行参数类型不匹配

● edit_file(src/utils.py)
  ⎿ 修改成功

● write_file(tests/test_utils.py)
  ⎿ 写入测试文件

● bash(pytest tests/test_utils.py -v)
  ⎿ 3 passed
```

### PLAN 模式 - 复杂任务先规划再执行

```
[BUILD] ❯ 把项目的 docs 目录部署到文档网站

● enter_plan_mode()
  ⎿ 已进入 PLAN 模式

● glob(docs/**/*.md)
  ⎿ 找到 5 个文档文件

● write_file(~/.lumos/plans/bright-calm-aurora.md)
  ⎿ 写入实现计划

请审批此计划:
- 输入 'approve' 批准并切换到 BUILD 模式
- 输入 'reject' 继续规划

[用户输入] approve

● 已切换到 BUILD 模式，开始执行计划...
● bash(pip install mkdocs-material)
● write_file(mkdocs.yml)

✅ 部署完成！
```

### Skill 系统 - 可扩展能力

```bash
# 查看已安装 Skills
[BUILD] ❯ /skills list

📦 本地 Skills (~/.lumos/skills/)
  - code-review: 代码审查专家
  - git-commit: 智能提交助手

# 安装社区插件
[BUILD] ❯ /skills install example-skills@anthropics
  ⎿ 安装完成！新增 12 个 skills

# 使用 Skill
[BUILD] ❯ /pdf 分析 report.pdf 并提取关键数据
● 激活 Skill: pdf
● read_file(report.pdf)
  ⎿ 解析 PDF (32 页)
```

## 命令参考

```bash
/mode build|plan|review    # 切换模式
/skills list               # 列出所有可用 skills
/skills install <plugin>@<marketplace>  # 安装插件
/help                      # 显示帮助
/clear                     # 清除对话历史
/exit                      # 退出程序
```

## 技术架构

### 核心设计

| 设计 | 说明 |
|------|------|
| **自建 ReAct Loop** | 直接调用 Anthropic/OpenAI API，无中间 SDK |
| **双模型路由** | 主模型 (Sonnet) 40-50%，小模型 (Haiku) 50-60%，成本降 70% |
| **子Agent隔离** | 每个子Agent独立会话，互不污染，结果聚合到主Agent |
| **三层工具架构** | 低层(Read/Write/Bash) → 中层(Edit/Grep/Glob) → 高层(Task/TodoWrite) |
| **模式权限控制** | BUILD 全权限，PLAN 只读+预授权，REVIEW 专注审查 |

### 工具权限矩阵

| 工具 | BUILD | PLAN | REVIEW |
|------|-------|------|--------|
| Read/Grep/Glob | ✅ | ✅ | ✅ |
| Write/Edit | ✅ | ❌ | ❌ |
| Bash | ✅ | ⚠️ 只读 | ❌ |
| TodoWrite | ✅ | ✅ | ✅ |

## 项目结构

```
lumos/
├── packages/
│   ├── server/
│   │   ├── core/              # 自建核心 (ReAct Loop, LLM, Tool 抽象)
│   │   ├── agents/            # Agent 实现 (LumosAgent, ModeManager)
│   │   ├── tools/             # 工具集 (14+ 工具)
│   │   ├── skills/            # Skills 系统 (loader/matcher/executor/installer)
│   │   ├── prompts/           # System Prompts
│   │   ├── context/           # 上下文管理
│   │   └── api/               # Web API (FastAPI + WebSocket)
│   └── cli/                   # TUI 客户端 (prompt-toolkit + Rich)
├── tests/                     # 测试套件
├── config/                    # 配置文件
└── pyproject.toml
```

## 安全机制

- 命令黑名单（`rm -rf /`, `mkfs`, `format C:` 等）
- 路径限制（`/etc`, `/usr/bin`, `C:\Windows` 等）
- PLAN 模式禁止破坏性命令
- 超时控制（默认 120 秒）
- 跨平台安全检查（自动适配 Linux/macOS/Windows）

## 测试

```bash
# 运行所有测试
pytest tests/ -v

# 查看测试覆盖率
pytest --cov=packages/server --cov-report=html
```

## 贡献

欢迎贡献代码、报告问题或提出建议！

1. Fork 本项目
2. 创建特性分支 (`git checkout -b feature/AmazingFeature`)
3. 提交更改 (`git commit -m 'Add some AmazingFeature'`)
4. 推送到分支 (`git push origin feature/AmazingFeature`)
5. 开启 Pull Request

## 许可证

本项目基于 MIT 许可证开源 - 详见 [LICENSE](LICENSE) 文件

## 致谢

- [Claude Code](https://docs.anthropic.com/en/docs/claude-code) - 设计灵感来源
- [Anthropic](https://www.anthropic.com/) / [OpenAI](https://openai.com/) - LLM 提供商

---

**项目地址**: https://github.com/SallyKAN/lumos
