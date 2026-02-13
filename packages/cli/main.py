"""
Lumos CLI — 交互式命令行界面

基于自建 ReAct Agent 核心，无 SDK 依赖。
"""

import os
import sys
import asyncio
import getpass
import logging
from pathlib import Path
from typing import Optional

from prompt_toolkit import PromptSession
from prompt_toolkit.formatted_text import ANSI
from prompt_toolkit.completion import Completer, Completion
from prompt_toolkit.patch_stdout import patch_stdout

from packages.server.utils.platform_compat import set_file_permissions

logger = logging.getLogger(__name__)

# ============================================================================
# 常量
# ============================================================================

VERSION = "0.1.0"
LUMOS_CONFIG_DIR = Path.home() / ".lumos"
LUMOS_CONFIG_FILE = LUMOS_CONFIG_DIR / "config.yaml"


class Colors:
    """ANSI 颜色常量"""
    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    RED = "\033[31m"
    GREEN = "\033[32m"
    YELLOW = "\033[33m"
    BLUE = "\033[34m"
    MAGENTA = "\033[35m"
    CYAN = "\033[36m"
    WHITE = "\033[37m"
    BRIGHT_RED = "\033[91m"
    BRIGHT_GREEN = "\033[92m"
    BRIGHT_YELLOW = "\033[93m"
    BRIGHT_BLUE = "\033[94m"
    BRIGHT_MAGENTA = "\033[95m"
    BRIGHT_CYAN = "\033[96m"
    BRIGHT_WHITE = "\033[97m"


# 工具显示名称映射
TOOL_DISPLAY_NAMES = {
    "read_file": "Read",
    "write_file": "Write",
    "edit_file": "Edit",
    "bash": "Bash",
    "grep": "Grep",
    "glob": "Glob",
    "ls": "LS",
    "web_search": "WebSearch",
    "web_fetch": "WebFetch",
    "todo_write": "TodoWrite",
    "ask_user_question": "AskUser",
    "browser_open": "BrowserOpen",
    "browser_snapshot": "BrowserSnapshot",
    "browser_click": "BrowserClick",
    "browser_type": "BrowserType",
    "browser_close": "BrowserClose",
    "exit_plan_mode": "ExitPlanMode",
    "enter_plan_mode": "EnterPlanMode",
    "send_email": "SendEmail",
}


def get_tool_display_name(tool_name: str, args: dict = None) -> str:
    """获取工具的友好显示名称"""
    if tool_name == "write_file" and args:
        file_path = args.get("file_path", "")
        if file_path and Path(file_path).exists():
            return "Update"
    return TOOL_DISPLAY_NAMES.get(tool_name, tool_name)


# Lumos ASCII Art Logo
LOGO_ART = r"""
  _
 | |    _   _ _ __ ___   ___  ___
 | |   | | | | '_ ` _ \ / _ \/ __|
 | |___| |_| | | | | | | (_) \__ \
 |______\__,_|_| |_| |_|\___/|___/
"""

LOGO_ART_COMPACT = r"""
  ╦   ╦ ╦╔╦╗╔═╗╔═╗
  ║   ║ ║║║║║ ║╚═╗
  ╩═╝╚═╝╩ ╩╚═╝╚═╝
"""

LOGO_MINI = "✦ Lumos"


# ============================================================================
# 配置管理
# ============================================================================

def get_default_api_base(provider: str) -> str:
    """获取默认 API Base URL"""
    defaults = {
        "anthropic": "https://api.anthropic.com",
        "openai": "https://api.openai.com/v1",
        "zhipu": "https://open.bigmodel.cn/api/paas/v4",
        "custom": ""
    }
    return defaults.get(provider, "")


def get_default_model(provider: str) -> str:
    """获取默认模型"""
    defaults = {
        "anthropic": "claude-sonnet-4-5-20250929",
        "openai": "gpt-4o",
        "zhipu": "glm-4",
        "custom": ""
    }
    return defaults.get(provider, "")


def get_config() -> dict:
    """读取配置文件

    优先级：配置文件 > 环境变量 > 默认值
    """
    config = {
        "api_key": None,
        "api_base_url": None,
        "provider": "anthropic",
        "model": "claude-sonnet-4-5-20250929"
    }

    # 1. 首先从配置文件读取（最高优先级）
    if LUMOS_CONFIG_FILE.exists():
        try:
            import yaml
            with open(LUMOS_CONFIG_FILE, 'r') as f:
                file_config = yaml.safe_load(f) or {}
                if file_config.get("api_key"):
                    config["api_key"] = file_config["api_key"]
                if file_config.get("api_base_url"):
                    config["api_base_url"] = file_config["api_base_url"]
                if file_config.get("provider"):
                    config["provider"] = file_config["provider"]
                if file_config.get("model"):
                    config["model"] = file_config["model"]
        except Exception:
            pass

    # 2. 如果配置文件没有 api_key，从环境变量读取
    if not config["api_key"]:
        env_key_map = {
            "anthropic": "ANTHROPIC_API_KEY",
            "openai": "OPENAI_API_KEY",
            "zhipu": "ZHIPU_API_KEY",
        }
        env_var = env_key_map.get(config["provider"])
        if env_var:
            config["api_key"] = os.environ.get(env_var)

        if not config["api_key"]:
            config["api_key"] = (os.environ.get("ANTHROPIC_API_KEY") or
                                 os.environ.get("OPENAI_API_KEY") or
                                 os.environ.get("ZHIPU_API_KEY"))

    # 3. 如果配置文件没有 api_base_url，从环境变量读取
    if not config["api_base_url"]:
        config["api_base_url"] = (os.environ.get("API_BASE_URL") or
                                  os.environ.get("ANTHROPIC_API_BASE") or
                                  os.environ.get("OPENAI_API_BASE"))

    # 4. 如果还是没有 api_base_url，使用默认值
    if not config["api_base_url"]:
        config["api_base_url"] = get_default_api_base(config["provider"])

    return config


def save_config(api_key: str, provider: str = "anthropic",
                model: str = None, api_base_url: str = None):
    """保存配置到文件"""
    LUMOS_CONFIG_DIR.mkdir(parents=True, exist_ok=True)

    config = {
        "api_key": api_key,
        "provider": provider,
    }
    if api_base_url:
        config["api_base_url"] = api_base_url
    if model:
        config["model"] = model

    try:
        import yaml
        with open(LUMOS_CONFIG_FILE, 'w') as f:
            yaml.dump(config, f, default_flow_style=False)
    except ImportError:
        with open(LUMOS_CONFIG_FILE, 'w') as f:
            f.write(f"api_key: {api_key}\n")
            f.write(f"provider: {provider}\n")
            if api_base_url:
                f.write(f"api_base_url: {api_base_url}\n")
            if model:
                f.write(f"model: {model}\n")

    set_file_permissions(LUMOS_CONFIG_FILE, 0o600)


def prompt_api_key_setup() -> bool:
    """交互式提示用户配置 API Key"""
    print()
    print(f"  {Colors.BRIGHT_YELLOW}⚠{Colors.RESET}  未检测到 API Key 配置")
    print()
    print(f"  {Colors.DIM}Lumos 需要 API Key 才能运行。{Colors.RESET}")
    print(f"  {Colors.DIM}您可以从 https://console.anthropic.com 获取 Anthropic API Key。{Colors.RESET}")
    print()

    while True:
        try:
            response = input(
                f"  {Colors.BRIGHT_CYAN}?{Colors.RESET} 是否现在配置 API Key? "
                f"{Colors.DIM}(Y/n){Colors.RESET} "
            ).strip().lower()
            if response in ('', 'y', 'yes', '是'):
                break
            elif response in ('n', 'no', '否'):
                print()
                print(f"  {Colors.DIM}您可以稍后通过以下方式配置:{Colors.RESET}")
                print(f"    • 运行 {Colors.BRIGHT_WHITE}lumos --config{Colors.RESET}")
                print(f"    • 设置环境变量 {Colors.BRIGHT_WHITE}ANTHROPIC_API_KEY{Colors.RESET}")
                print(f"    • 编辑配置文件 {Colors.BRIGHT_WHITE}~/.lumos/config.yaml{Colors.RESET}")
                print()
                return False
        except (KeyboardInterrupt, EOFError):
            print()
            return False

    print()

    # 选择 Provider
    print(f"  {Colors.BRIGHT_CYAN}?{Colors.RESET} 选择 API 提供商:")
    print(f"    {Colors.BRIGHT_WHITE}1{Colors.RESET}. Anthropic (Claude)")
    print(f"    {Colors.BRIGHT_WHITE}2{Colors.RESET}. OpenAI (GPT)")
    print(f"    {Colors.BRIGHT_WHITE}3{Colors.RESET}. 智谱 (GLM-4) {Colors.DIM}[国产推荐]{Colors.RESET}")
    print(f"    {Colors.BRIGHT_WHITE}4{Colors.RESET}. 其他 (自定义)")
    print()

    provider = "anthropic"
    model = None
    api_base_url = None

    while True:
        try:
            choice = input(f"  {Colors.DIM}请输入选项 (1-4) [1]:{Colors.RESET} ").strip()
            if choice in ('', '1'):
                provider = "anthropic"
                model = get_default_model("anthropic")
                break
            elif choice == '2':
                provider = "openai"
                model = get_default_model("openai")
                break
            elif choice == '3':
                provider = "zhipu"
                model = get_default_model("zhipu")
                break
            elif choice == '4':
                provider = "custom"
                break
            else:
                print(f"  {Colors.RED}无效选项，请输入 1-4{Colors.RESET}")
        except (KeyboardInterrupt, EOFError):
            print()
            return False

    print()

    # 输入 API Base URL
    default_api_base = get_default_api_base(provider)
    print(f"  {Colors.BRIGHT_CYAN}?{Colors.RESET} 请输入 API Base URL:")
    if default_api_base:
        print(f"  {Colors.DIM}按 Enter 使用默认值: {default_api_base}{Colors.RESET}")
    else:
        print(f"  {Colors.DIM}例如: https://api.example.com/v1{Colors.RESET}")
    print()

    try:
        api_base_input = input(f"  {Colors.DIM}API Base URL:{Colors.RESET} ").strip()
        if api_base_input:
            api_base_url = api_base_input
        else:
            api_base_url = default_api_base
    except (KeyboardInterrupt, EOFError):
        print()
        return False

    print()

    # 输入 API Key
    api_key_label = {
        "anthropic": "Anthropic API Key",
        "openai": "OpenAI API Key",
        "zhipu": "智谱 API Key",
        "custom": "API Key"
    }.get(provider, "API Key")

    print(f"  {Colors.BRIGHT_CYAN}?{Colors.RESET} 请输入 {api_key_label}:")
    print(f"  {Colors.DIM}(输入内容不会显示在屏幕上){Colors.RESET}")
    print()

    try:
        api_key = getpass.getpass(f"  {Colors.DIM}API Key:{Colors.RESET} ")
        if not api_key.strip():
            print(f"  {Colors.RED}API Key 不能为空{Colors.RESET}")
            return False
        api_key = api_key.strip()
    except (KeyboardInterrupt, EOFError):
        print()
        return False

    # 验证 API Key 格式
    if provider == "anthropic" and not api_key.startswith("sk-ant-"):
        print()
        print(f"  {Colors.BRIGHT_YELLOW}⚠{Colors.RESET}  API Key 格式看起来不正确")
        print(f"  {Colors.DIM}Anthropic API Key 通常以 'sk-ant-' 开头{Colors.RESET}")
        try:
            confirm = input(
                f"  {Colors.DIM}是否仍要保存? (y/N):{Colors.RESET} "
            ).strip().lower()
            if confirm not in ('y', 'yes', '是'):
                return False
        except (KeyboardInterrupt, EOFError):
            print()
            return False

    # 保存配置
    print()
    print(f"  {Colors.DIM}正在保存配置...{Colors.RESET}")

    try:
        save_config(api_key, provider, model, api_base_url)
        print(f"  {Colors.BRIGHT_GREEN}✓{Colors.RESET} 配置已保存到 "
              f"{Colors.BRIGHT_WHITE}~/.lumos/config.yaml{Colors.RESET}")
        print()

        env_var = {
            "anthropic": "ANTHROPIC_API_KEY",
            "openai": "OPENAI_API_KEY",
            "zhipu": "ZHIPU_API_KEY"
        }.get(provider, "API_KEY")
        os.environ[env_var] = api_key
        if api_base_url:
            os.environ["API_BASE_URL"] = api_base_url

        return True
    except Exception as e:
        print(f"  {Colors.RED}✗{Colors.RESET} 保存配置失败: {e}")
        return False


def check_and_setup_config() -> bool:
    """检查配置，如果需要则引导用户设置"""
    config = get_config()
    if config.get("api_key"):
        return True
    return prompt_api_key_setup()


# ============================================================================
# 欢迎界面
# ============================================================================

def print_welcome_screen():
    """打印欢迎界面"""
    print("\033[2J\033[H", end="")

    print()
    print(f"  {Colors.DIM}●{Colors.RESET} Welcome to the "
          f"{Colors.BRIGHT_CYAN}Lumos{Colors.RESET} research preview!")
    print()

    lines = LOGO_ART.strip().split('\n')
    glow_colors = [
        "\033[38;5;228m", "\033[38;5;227m", "\033[38;5;226m",
        "\033[38;5;220m", "\033[38;5;214m",
    ]

    color_idx = 0
    for line in lines:
        if line.strip():
            color = glow_colors[color_idx % len(glow_colors)]
            print(f"  {color}{line}{Colors.RESET}")
            color_idx += 1
        else:
            print()

    print()
    print(f"  {Colors.BRIGHT_GREEN}●{Colors.RESET} Login successful. "
          f"Press {Colors.BOLD}Enter{Colors.RESET} to continue")
    print()


# ============================================================================
# 命令自动补全
# ============================================================================

class SlashCommandCompleter(Completer):
    """/ 命令自动补全器，支持动态 skill 命令"""

    COMMANDS = [
        ("/help", "显示帮助信息"),
        ("/mode", "显示当前模式"),
        ("/tools", "显示可用工具"),
        ("/skills", "显示可用 skills"),
        ("/skill", "激活指定 skill"),
        ("/skill install", "安装远程 skill 插件"),
        ("/skill uninstall", "卸载 skill 插件"),
        ("/skill update", "更新 skill 插件"),
        ("/skill list-installed", "列出已安装的插件"),
        ("/sessions", "列出历史会话"),
        ("/resume", "恢复历史会话"),
        ("/pause", "暂停当前会话"),
        ("/status", "显示当前会话状态"),
        ("/build", "切换到 BUILD 模式"),
        ("/plan", "切换到 PLAN 模式"),
        ("/review", "切换到 REVIEW 模式"),
        ("/config", "显示配置信息"),
        ("/clear", "清屏"),
        ("/exit", "退出程序"),
        ("/quit", "退出程序"),
    ]

    def __init__(self, skill_manager=None):
        self.skill_manager = skill_manager

    def get_completions(self, document, complete_event):
        text = document.text_before_cursor

        if not text.startswith("/"):
            return

        word = text.lower()

        for cmd, desc in self.COMMANDS:
            if cmd.startswith(word):
                yield Completion(
                    cmd,
                    start_position=-len(text),
                    display_meta=desc
                )

        if self.skill_manager:
            for skill in self.skill_manager.list_skills():
                skill_cmd = f"/{skill.metadata.name}"
                if skill_cmd.lower().startswith(word):
                    yield Completion(
                        skill_cmd,
                        start_position=-len(text),
                        display_meta=skill.metadata.description[:40] + "..." if len(skill.metadata.description) > 40 else skill.metadata.description
                    )


# ============================================================================
# 交互式 CLI
# ============================================================================

class LumosCLI:
    """Lumos 交互式命令行界面"""

    def __init__(self, config: dict):
        self.config = config
        self.running = True
        self.session_id = f"session_{os.getpid()}"
        self._interrupted = False
        self._current_task = None
        self._cancelled_task = None
        self._message_count = 0
        self._session_created = False

        # 延迟导入 Rich
        try:
            from rich.console import Console
            from rich.panel import Panel
            from rich.markdown import Markdown
            from rich.table import Table
            self.console = Console()
            self.has_rich = True
        except ImportError:
            self.console = None
            self.has_rich = False

        # 初始化会话管理器
        self.session_manager = None
        self._init_session_manager()

        # 初始化 Lumos Agent
        self.agent = None
        self._init_agent()

    def _init_session_manager(self):
        """初始化会话管理器"""
        try:
            from packages.server.session.session_manager import SessionManager, migrate_todos_to_sessions
            self.session_manager = SessionManager()

            migrated = migrate_todos_to_sessions()
            if migrated > 0:
                print(f"  {Colors.DIM}✓ 已迁移 {migrated} 个历史会话{Colors.RESET}")
        except Exception as e:
            self._print(f"  {Colors.BRIGHT_YELLOW}⚠{Colors.RESET} 会话管理器初始化警告: {e}")
            self.session_manager = None

    def _init_agent(self):
        """初始化 Lumos Agent"""
        try:
            from packages.server.agents.lumos_agent import LumosAgent

            api_key = self.config.get("api_key")
            provider = self.config.get("provider", "openai")
            model = self.config.get("model")
            api_base = self.config.get("api_base_url")

            self.agent = LumosAgent(
                model_provider=provider,
                api_key=api_key,
                api_base=api_base,
                model_name=model or "gpt-4o",
                session_id=self.session_id,
            )

        except Exception as e:
            self._print(f"  {Colors.BRIGHT_YELLOW}⚠{Colors.RESET} Agent 初始化警告: {e}")
            self.agent = None

    def _print(self, text: str, **kwargs):
        """打印输出"""
        if self.has_rich and self.console:
            import re
            if '\033[' in text:
                print(text)
            else:
                self.console.print(text, **kwargs)
        else:
            import re
            clean_text = re.sub(r'\[.*?\]', '', text)
            print(clean_text)

    def show_welcome(self, style: str = "compact"):
        """显示欢迎信息"""
        print("\033[2J\033[H", end="")

        provider = self.config.get("provider", "unknown")
        model = self.config.get("model", "unknown")
        mode = self.agent.get_current_mode().value.upper() if self.agent else "BUILD"
        cwd = os.getcwd()
        home = str(Path.home())
        if cwd.startswith(home):
            cwd = "~" + cwd[len(home):]

        if style == "mini":
            print()
            print(f" {Colors.BRIGHT_CYAN}✦{Colors.RESET}  {Colors.BOLD}Lumos{Colors.RESET} v{VERSION}")
            print(f"    {Colors.BRIGHT_WHITE}{model}{Colors.RESET} · {Colors.DIM}{provider}{Colors.RESET}")
            print(f"    {Colors.DIM}{cwd}{Colors.RESET}")
            print()
            print(f"  {Colors.BRIGHT_GREEN}Welcome to {model}{Colors.RESET}")
            print()
            term_width = os.get_terminal_size().columns if hasattr(os, 'get_terminal_size') else 80
            print(f"{Colors.DIM}{'─' * term_width}{Colors.RESET}")
        else:
            # 紧凑版风格
            logo_lines = [line for line in LOGO_ART_COMPACT.splitlines() if line.strip()]

            gradient_colors = [
                "\033[38;5;228m",  # 亮黄色
                "\033[38;5;227m",  # 黄色
                "\033[38;5;226m",  # 金黄色
            ]

            print()
            for i, line in enumerate(logo_lines):
                color = gradient_colors[i % len(gradient_colors)]
                print(f"  {color}{line}{Colors.RESET}")

            # 状态行
            print()
            print(f"  {Colors.DIM}v{VERSION}{Colors.RESET} | "
                  f"{Colors.DIM}Provider:{Colors.RESET} {Colors.BRIGHT_CYAN}{provider}{Colors.RESET} | "
                  f"{Colors.DIM}Model:{Colors.RESET} {Colors.BRIGHT_CYAN}{model}{Colors.RESET} | "
                  f"{Colors.DIM}Mode:{Colors.RESET} {Colors.BRIGHT_GREEN}{mode}{Colors.RESET}")
            print()

            # 快捷命令框
            box_width = 80
            border_char = "─"

            print(f"{Colors.DIM}╭─ 快捷命令 {border_char * (box_width - 14)}╮{Colors.RESET}")
            print(f"{Colors.DIM}│{Colors.RESET}  "
                  f"{Colors.BRIGHT_WHITE}/help{Colors.RESET} {Colors.DIM}- 帮助{Colors.RESET}  "
                  f"{Colors.BRIGHT_WHITE}/mode{Colors.RESET} {Colors.DIM}- 模式{Colors.RESET}  "
                  f"{Colors.BRIGHT_WHITE}/tools{Colors.RESET} {Colors.DIM}- 工具{Colors.RESET}  "
                  f"{Colors.BRIGHT_WHITE}/exit{Colors.RESET} {Colors.DIM}- 退出{Colors.RESET}  "
                  f"{Colors.BRIGHT_WHITE}Esc{Colors.RESET} {Colors.DIM}- 中断任务{Colors.RESET}  "
                  f"{Colors.DIM}│{Colors.RESET}")
            print(f"{Colors.DIM}╰{border_char * box_width}╯{Colors.RESET}")
            print()

    def show_help(self):
        """显示帮助"""
        if not self.has_rich:
            print("\n可用命令:")
            print("  /help                - 显示帮助")
            print("  /mode                - 显示当前模式")
            print("  /tools               - 显示可用工具")
            print("  /skills              - 显示可用 skills")
            print("  /skill <name>        - 激活指定 skill")
            print("  /skill install <plugin>@<marketplace> - 安装远程插件")
            print("  /skill uninstall <plugin>@<marketplace> - 卸载插件")
            print("  /skill update <plugin>@<marketplace> - 更新插件")
            print("  /skill list-installed - 列出已安装插件")
            print("  /build               - 切换到 BUILD 模式")
            print("  /plan                - 切换到 PLAN 模式")
            print("  /review              - 切换到 REVIEW 模式")
            print("  /sessions            - 显示历史会话列表")
            print("  /resume [id]         - 恢复历史会话")
            print("  /pause               - 暂停当前会话")
            print("  /status              - 显示当前会话状态")
            print("  /config              - 显示配置信息")
            print("  /clear               - 清除屏幕")
            print("  /exit                - 退出程序")
            print()
            return

        from rich.table import Table

        table = Table(title="📖 可用命令", border_style="cyan")
        table.add_column("命令", style="cyan", width=40)
        table.add_column("说明")

        commands = [
            ("/help", "显示此帮助"),
            ("/mode", "显示当前模式信息"),
            ("/tools", "显示可用工具列表"),
            ("/skills", "显示可用 skills 列表"),
            ("/skill <name>", "激活指定 skill"),
            ("/skill install <plugin>@<marketplace>", "安装远程 skill 插件"),
            ("/skill uninstall <plugin>@<marketplace>", "卸载 skill 插件"),
            ("/skill update <plugin>@<marketplace>", "更新 skill 插件"),
            ("/skill list-installed", "列出已安装的插件"),
            ("/build", "切换到 BUILD 模式 - 完全开发权限"),
            ("/plan", "切换到 PLAN 模式 - 只读分析"),
            ("/review", "切换到 REVIEW 模式 - 代码审查"),
            ("/sessions", "显示历史会话列表"),
            ("/resume [session_id]", "恢复历史会话"),
            ("/pause", "暂停当前会话"),
            ("/status", "显示当前会话状态"),
            ("/config", "显示配置信息"),
            ("/clear", "清除屏幕"),
            ("/exit", "退出程序"),
        ]

        for cmd, desc in commands:
            table.add_row(cmd, desc)

        self.console.print(table)

    def show_mode(self):
        """显示当前模式"""
        if not self.agent:
            self._print("[yellow]Agent 未初始化[/yellow]")
            return

        info = self.agent.get_mode_info()
        mode = info['mode'].upper()

        if not self.has_rich:
            print(f"\n当前模式: {mode}")
            print(f"只读: {'是' if info['read_only'] else '否'}")
            print()
            return

        from rich.panel import Panel
        from rich.markdown import Markdown

        mode_desc = {
            "BUILD": ("🔨", "完全开发权限，可以修改文件和执行命令"),
            "PLAN": ("🔍", "只读模式，用于代码探索和规划"),
            "REVIEW": ("📝", "代码审查模式，专注于代码质量分析"),
        }

        emoji, desc = mode_desc.get(mode, ("❓", "未知模式"))

        panel_content = f"""
{emoji} **{mode} 模式**

{desc}

**只读**: {'是' if info['read_only'] else '否'}
**可用工具**: {len(info['allowed_tools'])} 个
"""

        self.console.print(Panel(
            Markdown(panel_content),
            title="当前模式",
            border_style="green" if mode == "BUILD" else "blue"
        ))

    def show_tools(self):
        """显示可用工具"""
        if not self.agent:
            self._print("[yellow]Agent 未初始化[/yellow]")
            return

        tools = self.agent.get_available_tools()
        mode = self.agent.get_current_mode().value.upper()

        if not self.has_rich:
            print(f"\n可用工具 ({mode} 模式):")
            for tool in tools:
                print(f"  - {tool}")
            print()
            return

        from rich.table import Table

        table = Table(title=f"🔧 可用工具 ({mode} 模式)", border_style="cyan")
        table.add_column("工具", style="cyan")
        table.add_column("类型", style="dim")

        tool_types = {
            "read_file": "低层 - 文件读取",
            "write_file": "低层 - 文件写入",
            "edit_file": "中层 - 文件编辑",
            "bash": "低层 - Shell 命令",
            "grep": "中层 - 内容搜索",
            "glob": "中层 - 文件匹配",
            "ls": "中层 - 目录列表",
        }

        for tool in sorted(tools):
            tool_type = tool_types.get(tool, "其他")
            table.add_row(tool, tool_type)

        self.console.print(table)

    def show_skills(self):
        """显示可用 skills"""
        if not self.agent:
            self._print("[yellow]Agent 未初始化[/yellow]")
            return

        skills = self.agent.list_skills()
        current_skill = self.agent.get_current_skill()

        if not skills:
            print(f"\n  {Colors.DIM}暂无可用的 skills{Colors.RESET}")
            print(f"  {Colors.DIM}在 ~/.lumos/skills/ 目录下创建 skill{Colors.RESET}\n")
            return

        if not self.has_rich:
            print(f"\n可用 Skills:")
            for skill in skills:
                active = " (激活)" if current_skill and skill.name == current_skill.name else ""
                print(f"  - {skill.name}{active}")
                if skill.description:
                    print(f"    {skill.description[:60]}...")
            print()
            return

        from rich.table import Table

        table = Table(title="🎯 可用 Skills", border_style="magenta")
        table.add_column("名称", style="magenta")
        table.add_column("来源", style="dim")
        table.add_column("描述", style="white")
        table.add_column("状态", style="green")

        for skill in skills:
            source = skill.source.value
            desc = skill.description[:50] + "..." if len(skill.description) > 50 else skill.description
            status = "✓ 激活" if current_skill and skill.name == current_skill.name else ""
            table.add_row(skill.name, source, desc, status)

        self.console.print(table)
        print(f"\n  {Colors.DIM}使用 /skill <name> 激活 skill{Colors.RESET}\n")

    def activate_skill(self, skill_name: str):
        """激活指定的 skill"""
        if not self.agent:
            self._print("[yellow]Agent 未初始化[/yellow]")
            return

        if self.agent.activate_skill(skill_name):
            skill = self.agent.get_current_skill()
            print(f"\n  {Colors.GREEN}✓ 已激活 skill: {skill_name}{Colors.RESET}")
            if skill and skill.allowed_tools:
                tools_str = ", ".join(sorted(skill.allowed_tools))
                print(f"  {Colors.DIM}允许的工具: {tools_str}{Colors.RESET}")
            print()
        else:
            print(f"\n  {Colors.YELLOW}未找到 skill: {skill_name}{Colors.RESET}")
            print(f"  {Colors.DIM}使用 /skills 查看可用的 skills{Colors.RESET}\n")

    def deactivate_skill(self):
        """停用当前 skill"""
        if not self.agent:
            return
        current = self.agent.get_current_skill()
        if current:
            self.agent.deactivate_skill()
            print(f"\n  {Colors.YELLOW}已停用 skill: {current.name}{Colors.RESET}\n")
        else:
            print(f"\n  {Colors.DIM}当前没有激活的 skill{Colors.RESET}\n")

    def install_plugin(self, spec: str):
        """安装远程插件"""
        if not self.agent:
            self._print("[yellow]Agent 未初始化[/yellow]")
            return
        print(f"\n  {Colors.CYAN}正在安装插件: {spec}{Colors.RESET}")
        print(f"  {Colors.DIM}这可能需要一些时间...{Colors.RESET}\n")
        try:
            plugin = self.agent.skill_manager.install_plugin(spec)
            print(f"  {Colors.GREEN}✓ 安装成功!{Colors.RESET}")
            print(f"    插件: {plugin.plugin_name}")
            print(f"    来源: {plugin.marketplace}")
            print(f"    Skills: {', '.join(plugin.skills)}")
            print(f"    路径: {plugin.install_path}")
            print()
        except Exception as e:
            print(f"  {Colors.RED}✗ 安装失败: {e}{Colors.RESET}\n")

    def uninstall_plugin(self, spec: str):
        """卸载插件"""
        if not self.agent:
            self._print("[yellow]Agent 未初始化[/yellow]")
            return
        print(f"\n  {Colors.CYAN}正在卸载插件: {spec}{Colors.RESET}\n")
        try:
            self.agent.skill_manager.uninstall_plugin(spec)
            print(f"  {Colors.GREEN}✓ 卸载成功!{Colors.RESET}\n")
        except Exception as e:
            print(f"  {Colors.RED}✗ 卸载失败: {e}{Colors.RESET}\n")

    def update_plugin(self, spec: str):
        """更新插件"""
        if not self.agent:
            self._print("[yellow]Agent 未初始化[/yellow]")
            return
        print(f"\n  {Colors.CYAN}正在更新插件: {spec}{Colors.RESET}")
        print(f"  {Colors.DIM}这可能需要一些时间...{Colors.RESET}\n")
        try:
            plugin = self.agent.skill_manager.update_plugin(spec)
            print(f"  {Colors.GREEN}✓ 更新成功!{Colors.RESET}")
            print(f"    插件: {plugin.plugin_name}")
            print(f"    Skills: {', '.join(plugin.skills)}")
            print()
        except Exception as e:
            print(f"  {Colors.RED}✗ 更新失败: {e}{Colors.RESET}\n")

    def list_installed_plugins(self):
        """列出已安装的插件"""
        if not self.agent:
            self._print("[yellow]Agent 未初始化[/yellow]")
            return
        plugins = self.agent.skill_manager.list_installed_plugins()
        if not plugins:
            print(f"\n  {Colors.DIM}暂无已安装的插件{Colors.RESET}")
            print(f"  {Colors.DIM}使用 /skill install <plugin>@<marketplace> 安装插件{Colors.RESET}\n")
            return
        if not self.has_rich:
            print(f"\n已安装的插件:")
            for plugin in plugins:
                print(f"  - {plugin.spec}")
                print(f"    Skills: {', '.join(plugin.skills)}")
                print(f"    安装时间: {plugin.installed_at.strftime('%Y-%m-%d %H:%M')}")
            print()
            return
        from rich.table import Table
        table = Table(title="📦 已安装的插件", border_style="green")
        table.add_column("插件", style="green")
        table.add_column("Skills", style="cyan")
        table.add_column("安装时间", style="dim")
        for plugin in plugins:
            skills_str = ", ".join(plugin.skills[:3])
            if len(plugin.skills) > 3:
                skills_str += f" (+{len(plugin.skills) - 3})"
            table.add_row(
                plugin.spec,
                skills_str,
                plugin.installed_at.strftime('%Y-%m-%d %H:%M')
            )
        self.console.print(table)
        print()

    def show_config(self):
        """显示配置信息"""
        config = self.config
        api_key = config.get("api_key", "")
        masked_key = f"{'*' * 16}...{api_key[-4:]}" if api_key else "未配置"
        print()
        print(f"  {Colors.BOLD}配置信息{Colors.RESET}")
        print(f"    Provider:     {Colors.BRIGHT_CYAN}{config.get('provider', 'unknown')}{Colors.RESET}")
        print(f"    API Base URL: {Colors.DIM}{config.get('api_base_url', 'default')}{Colors.RESET}")
        print(f"    API Key:      {Colors.DIM}{masked_key}{Colors.RESET}")
        print(f"    Model:        {Colors.BRIGHT_CYAN}{config.get('model', 'unknown')}{Colors.RESET}")
        print(f"    Config File:  {Colors.DIM}{LUMOS_CONFIG_FILE}{Colors.RESET}")
        print()

    def switch_mode(self, mode_name: str):
        """切换模式"""
        if not self.agent:
            self._print("[yellow]Agent 未初始化[/yellow]")
            return
        from packages.server.agents.mode_manager import AgentMode
        mode_map = {
            "build": AgentMode.BUILD,
            "plan": AgentMode.PLAN,
            "review": AgentMode.REVIEW
        }
        if mode_name not in mode_map:
            self._print(f"[red]无效模式: {mode_name}[/red]")
            return
        old = self.agent.get_current_mode()
        new = mode_map[mode_name]
        if self.agent.switch_mode(new):
            print(f"  {Colors.BRIGHT_GREEN}✓{Colors.RESET} 模式切换: "
                  f"{old.value.upper()} → {new.value.upper()}")
            tips = {
                "build": f"  {Colors.DIM}💡 BUILD 模式: 完全开发权限{Colors.RESET}",
                "plan": f"  {Colors.DIM}🔍 PLAN 模式: 只读模式{Colors.RESET}",
                "review": f"  {Colors.DIM}📝 REVIEW 模式: 代码审查{Colors.RESET}"
            }
            print(tips.get(mode_name, ''))
        else:
            print(f"  {Colors.YELLOW}已经是 {new.value.upper()} 模式{Colors.RESET}")

    def show_sessions(self, limit: int = 10):
        """显示历史会话列表"""
        if not self.session_manager:
            print(f"\n  {Colors.YELLOW}⚠ 会话管理器未初始化{Colors.RESET}\n")
            return
        project_path = os.getcwd()
        sessions = self.session_manager.list_sessions(project_path=project_path, limit=limit)
        if not sessions:
            print(f"\n  {Colors.DIM}暂无历史会话{Colors.RESET}")
            print(f"  {Colors.DIM}开始对话后会自动创建会话记录{Colors.RESET}\n")
            return
        if not self.has_rich:
            print(f"\n历史会话 (最近 {len(sessions)} 个):")
            for session in sessions:
                status_icon = "●" if session.status == "active" else "○"
                print(f"  {status_icon} {session.session_id}")
                print(f"    标题: {session.title}")
                print(f"    状态: {session.status}")
                try:
                    from datetime import datetime
                    updated_dt = datetime.fromisoformat(session.updated_at)
                    updated_str = updated_dt.strftime('%Y-%m-%d %H:%M')
                except (ValueError, TypeError):
                    updated_str = session.updated_at[:16] if session.updated_at else "未知"
                print(f"    更新: {updated_str}")
            print(f"\n  {Colors.DIM}使用 /resume <session_id> 恢复会话{Colors.RESET}\n")
            return
        from rich.table import Table
        table = Table(title=f"📋 历史会话 (最近 {len(sessions)} 个)", border_style="cyan")
        table.add_column("会话 ID", style="cyan", width=25)
        table.add_column("标题", style="white", width=30)
        table.add_column("状态", style="green", width=10)
        table.add_column("更新时间", style="dim", width=16)
        status_icons = {
            "active": f"{Colors.BRIGHT_GREEN}●{Colors.RESET}",
            "paused": f"{Colors.BRIGHT_YELLOW}◐{Colors.RESET}",
            "completed": f"{Colors.DIM}○{Colors.RESET}",
            "interrupted": f"{Colors.BRIGHT_RED}◌{Colors.RESET}",
        }
        for session in sessions:
            status_icon = status_icons.get(session.status, "○")
            title = session.title[:28] + "..." if len(session.title) > 28 else session.title
            try:
                from datetime import datetime
                updated_dt = datetime.fromisoformat(session.updated_at)
                updated_str = updated_dt.strftime('%Y-%m-%d %H:%M')
            except (ValueError, TypeError):
                updated_str = session.updated_at[:16] if session.updated_at else "未知"
            table.add_row(session.session_id, title, f"{status_icon} {session.status}", updated_str)
        self.console.print(table)
        print(f"\n  {Colors.DIM}使用 /resume <session_id> 恢复会话{Colors.RESET}\n")

    def resume_session(self, session_id: Optional[str] = None):
        """恢复历史会话"""
        if not self.session_manager:
            print(f"\n  {Colors.YELLOW}⚠ 会话管理器未初始化{Colors.RESET}\n")
            return
        if not session_id:
            self.show_sessions()
            return
        try:
            metadata, summary, todos = self.session_manager.load_session(session_id)
        except Exception as e:
            print(f"\n  {Colors.RED}✗ 加载会话失败: {e}{Colors.RESET}\n")
            return
        if metadata is None:
            print(f"\n  {Colors.YELLOW}⚠ 未找到会话: {session_id}{Colors.RESET}")
            print(f"  {Colors.DIM}使用 /sessions 查看可用的会话{Colors.RESET}\n")
            return
        self.session_id = session_id
        self.session_manager.update_status(session_id, "active")
        print(f"\n  {Colors.BRIGHT_GREEN}✓ 已恢复会话: {session_id}{Colors.RESET}")
        print(f"    {Colors.DIM}标题: {metadata.title}{Colors.RESET}")
        print(f"    {Colors.DIM}模式: {metadata.mode}{Colors.RESET}")
        print(f"    {Colors.DIM}消息数: {metadata.message_count}{Colors.RESET}")
        if summary:
            print(f"\n  {Colors.BOLD}上下文摘要:{Colors.RESET}")
            if summary.context:
                ctx = f"{summary.context[:100]}..." if len(summary.context) > 100 else summary.context
                print(f"    {Colors.DIM}{ctx}{Colors.RESET}")
            if summary.last_action:
                print(f"    {Colors.DIM}最后操作: {summary.last_action}{Colors.RESET}")
            if summary.interrupted_task:
                print(f"    {Colors.BRIGHT_YELLOW}⚠ 被中断的任务: {summary.interrupted_task}{Colors.RESET}")
        if todos:
            print(f"\n  {Colors.BOLD}任务列表:{Colors.RESET}")
            for todo in todos[:5]:
                if todo.status == "completed":
                    checkbox = f"{Colors.GREEN}☑{Colors.RESET}"
                elif todo.status == "in_progress":
                    checkbox = f"{Colors.YELLOW}◐{Colors.RESET}"
                else:
                    checkbox = f"{Colors.DIM}☐{Colors.RESET}"
                print(f"    {checkbox} {Colors.DIM}{todo.content}{Colors.RESET}")
            if len(todos) > 5:
                print(f"    {Colors.DIM}... 还有 {len(todos) - 5} 个任务{Colors.RESET}")
        print()

    def pause_session(self):
        """暂停当前会话"""
        if not self.session_manager:
            print(f"\n  {Colors.YELLOW}⚠ 会话管理器未初始化{Colors.RESET}\n")
            return
        if not self._session_created:
            print(f"\n  {Colors.YELLOW}⚠ 当前没有活动的会话{Colors.RESET}\n")
            return
        self._save_session_state(status="paused")
        print(f"\n  {Colors.BRIGHT_GREEN}✓ 会话已暂停: {self.session_id}{Colors.RESET}")
        print(f"  {Colors.DIM}使用 /resume {self.session_id} 恢复会话{Colors.RESET}\n")

    def show_session_status(self):
        """显示当前会话状态"""
        print(f"\n  {Colors.BOLD}📊 会话状态{Colors.RESET}")
        print(f"    {Colors.DIM}会话 ID:{Colors.RESET} {Colors.CYAN}{self.session_id}{Colors.RESET}")
        print(f"    {Colors.DIM}消息数:{Colors.RESET} {self._message_count}")
        mode = "BUILD"
        if self.agent:
            mode = self.agent.get_current_mode().value.upper()
        print(f"    {Colors.DIM}当前模式:{Colors.RESET} {Colors.BRIGHT_GREEN}{mode}{Colors.RESET}")
        if self._session_created:
            print(f"    {Colors.DIM}状态:{Colors.RESET} {Colors.BRIGHT_GREEN}● 活动中{Colors.RESET}")
        else:
            print(f"    {Colors.DIM}状态:{Colors.RESET} {Colors.DIM}○ 未保存{Colors.RESET}")
        cwd = os.getcwd()
        home = str(Path.home())
        if cwd.startswith(home):
            cwd = "~" + cwd[len(home):]
        print(f"    {Colors.DIM}项目路径:{Colors.RESET} {cwd}")
        if self.session_manager and self._session_created:
            try:
                metadata, summary, todos = self.session_manager.load_session(self.session_id)
                if metadata:
                    print(f"    {Colors.DIM}标题:{Colors.RESET} {metadata.title}")
                if todos:
                    completed = sum(1 for t in todos if t.status == "completed")
                    in_progress = sum(1 for t in todos if t.status == "in_progress")
                    pending = len(todos) - completed - in_progress
                    print(f"    {Colors.DIM}任务:{Colors.RESET} {Colors.GREEN}✓{completed}{Colors.RESET} {Colors.YELLOW}◐{in_progress}{Colors.RESET} {Colors.DIM}☐{pending}{Colors.RESET}")
            except Exception:
                pass
        print()

    def _create_session(self, first_message: str = ""):
        """创建新会话"""
        if not self.session_manager:
            return
        try:
            project_path = os.getcwd()
            self.session_id = self.session_manager.create_session(project_path)
            self._session_created = True
            title = first_message[:50] + "..." if len(first_message) > 50 else first_message
            if not title:
                title = "新会话"
            mode = "BUILD"
            if self.agent:
                mode = self.agent.get_current_mode().value.upper()
            from packages.server.session.session_manager import SessionMetadata
            from datetime import datetime
            now = datetime.now().isoformat()
            metadata = SessionMetadata(
                session_id=self.session_id, title=title, project_path=project_path,
                created_at=now, updated_at=now, mode=mode, status="active",
                message_count=0, tags=[]
            )
            self.session_manager.save_session(self.session_id, metadata=metadata)
        except Exception:
            pass

    def _save_session_state(self, status: str = "active"):
        """保存当前会话状态"""
        if not self.session_manager or not self._session_created:
            return
        try:
            metadata, summary, todos = self.session_manager.load_session(self.session_id)
            if metadata:
                from datetime import datetime
                metadata.updated_at = datetime.now().isoformat()
                metadata.message_count = self._message_count
                metadata.status = status
                if self.agent:
                    metadata.mode = self.agent.get_current_mode().value.upper()
                self.session_manager.save_session(self.session_id, metadata=metadata, summary=summary)
                self.session_manager.update_status(self.session_id, status)
        except Exception:
            pass

    def handle_command(self, user_input: str) -> tuple[bool, str | None]:
        """处理斜杠命令"""
        if not user_input.startswith("/"):
            return (False, None)
        parts = user_input.split()
        cmd = parts[0].lower()

        if cmd == "/exit" or cmd == "/quit":
            self.running = False
            print(f"\n  {Colors.YELLOW}👋 再见！{Colors.RESET}\n")
            return (True, None)
        elif cmd == "/help":
            self.show_help()
            return (True, None)
        elif cmd == "/mode":
            self.show_mode()
            return (True, None)
        elif cmd == "/tools":
            self.show_tools()
            return (True, None)
        elif cmd == "/skills":
            self.show_skills()
            return (True, None)
        elif cmd == "/skill":
            if len(parts) < 2:
                print(f"  {Colors.YELLOW}用法:{Colors.RESET}")
                print(f"    /skill <name>                    - 激活指定 skill")
                print(f"    /skill install <plugin>@<marketplace> - 安装远程插件")
                print(f"    /skill uninstall <plugin>@<marketplace> - 卸载插件")
                print(f"    /skill update <plugin>@<marketplace> - 更新插件")
                print(f"    /skill list-installed            - 列出已安装插件")
                print(f"  {Colors.DIM}使用 /skills 查看可用的 skills{Colors.RESET}")
                return (True, None)
            subcmd = parts[1].lower()
            if subcmd == "install":
                if len(parts) < 3:
                    print(f"  {Colors.YELLOW}用法: /skill install <plugin>@<marketplace>{Colors.RESET}")
                else:
                    self.install_plugin(parts[2])
                return (True, None)
            elif subcmd == "uninstall":
                if len(parts) < 3:
                    print(f"  {Colors.YELLOW}用法: /skill uninstall <plugin>@<marketplace>{Colors.RESET}")
                else:
                    self.uninstall_plugin(parts[2])
                return (True, None)
            elif subcmd == "update":
                if len(parts) < 3:
                    print(f"  {Colors.YELLOW}用法: /skill update <plugin>@<marketplace>{Colors.RESET}")
                else:
                    self.update_plugin(parts[2])
                return (True, None)
            elif subcmd == "list-installed":
                self.list_installed_plugins()
                return (True, None)
            else:
                self.activate_skill(subcmd)
            return (True, None)
        elif cmd == "/build":
            self.switch_mode("build")
            return (True, None)
        elif cmd == "/plan":
            self.switch_mode("plan")
            return (True, None)
        elif cmd == "/review":
            self.switch_mode("review")
            return (True, None)
        elif cmd == "/sessions":
            self.show_sessions()
            return (True, None)
        elif cmd == "/resume":
            session_id = parts[1] if len(parts) > 1 else None
            self.resume_session(session_id)
            return (True, None)
        elif cmd == "/pause":
            self.pause_session()
            return (True, None)
        elif cmd == "/status":
            self.show_session_status()
            return (True, None)
        elif cmd == "/config":
            self.show_config()
            return (True, None)
        elif cmd == "/clear":
            print("\033[2J\033[H", end="")
            self.show_welcome()
            return (True, None)
        else:
            if self.agent:
                skill_name = cmd[1:]
                skill = self.agent.skill_manager.get_skill(skill_name)
                if skill:
                    self.activate_skill(skill_name)
                    if len(parts) > 1:
                        pending_msg = " ".join(parts[1:])
                        return (True, pending_msg)
                    return (True, None)
            print(f"  {Colors.YELLOW}未知命令: {cmd}，使用 /help 查看可用命令{Colors.RESET}")
            return (True, None)
        return (False, None)

    async def _wait_for_escape(self, input_queue: asyncio.Queue = None):
        """监听 Esc 键或用户输入"""
        from prompt_toolkit.input import create_input
        from prompt_toolkit.keys import Keys
        input_obj = create_input()
        input_buffer = []
        try:
            while not self._interrupted:
                if getattr(self, '_pause_escape_listener', False):
                    await asyncio.sleep(0.1)
                    continue
                if input_queue:
                    try:
                        new_input = input_queue.get_nowait()
                        try:
                            from packages.server.intent.intent_classifier import IntentClassifier, InterruptIntent
                            classifier = IntentClassifier()
                            result = classifier.classify_sync(self._current_task_description, new_input)
                            if result.intent in (InterruptIntent.SWITCH, InterruptIntent.CANCEL, InterruptIntent.PAUSE, InterruptIntent.RESUME):
                                return (True, new_input)
                            else:
                                await input_queue.put(new_input)
                        except Exception:
                            return (True, new_input)
                    except asyncio.QueueEmpty:
                        pass
                with input_obj.raw_mode():
                    for key_press in input_obj.read_keys():
                        if key_press.key == Keys.Escape:
                            return (True, None)
                        elif key_press.key == Keys.Enter:
                            if input_buffer:
                                new_input = ''.join(input_buffer)
                                input_buffer.clear()
                                print()
                                return (True, new_input.strip())
                        elif key_press.key == Keys.ControlC:
                            return (True, None)
                        elif key_press.key == Keys.Backspace:
                            if input_buffer:
                                input_buffer.pop()
                                print('\b \b', end='', flush=True)
                        elif hasattr(key_press, 'data') and key_press.data:
                            char = key_press.data
                            if char.isprintable():
                                input_buffer.append(char)
                                print(f"{Colors.BRIGHT_YELLOW}{char}{Colors.RESET}", end='', flush=True)
                await asyncio.sleep(0.05)
        except Exception:
            pass
        return (False, None)

    async def process_message(self, user_input: str, input_queue: asyncio.Queue = None):
        """处理用户消息（支持 Esc 中断和新输入打断）"""
        if not self.agent:
            print(f"\n  {Colors.YELLOW}⚠️  Agent 未初始化{Colors.RESET}")
            return
        if not self.agent.api_key:
            print(f"\n  {Colors.YELLOW}⚠️  LLM 未配置，无法处理请求{Colors.RESET}")
            print(f"  {Colors.DIM}请运行 lumos --config 配置 API Key{Colors.RESET}\n")
            return
        self._interrupted = False
        self._pending_input = None
        print(f"\n{Colors.DIM}● 思考中...{Colors.RESET}")
        process_task = asyncio.create_task(self._do_process_message(user_input))
        input_task = asyncio.create_task(self._wait_for_escape(input_queue))
        done, pending = await asyncio.wait(
            [process_task, input_task], return_when=asyncio.FIRST_COMPLETED
        )
        if input_task in done:
            interrupted, new_input = input_task.result()
            if interrupted:
                self._interrupted = True
                process_task.cancel()
                try:
                    await process_task
                except asyncio.CancelledError:
                    pass
                if new_input:
                    self._pending_input = new_input
                    print(f"\n  {Colors.BRIGHT_YELLOW}● 收到新输入{Colors.RESET}")
                    try:
                        from packages.server.intent.intent_classifier import IntentClassifier, InterruptIntent
                        classifier = IntentClassifier()
                        result = classifier.classify_sync(user_input, new_input)
                        if result.intent == InterruptIntent.SWITCH:
                            print(f"  {Colors.DIM}→ 切换到新任务{Colors.RESET}")
                        elif result.intent == InterruptIntent.PAUSE:
                            print(f"  {Colors.DIM}→ 任务已暂停{Colors.RESET}")
                            if self.session_manager and self._session_created:
                                self._save_session_state(status="paused")
                            self._pending_input = None
                        elif result.intent == InterruptIntent.CANCEL:
                            print(f"  {Colors.DIM}→ 任务已取消{Colors.RESET}")
                            self._cancelled_task = user_input
                            print(f"  {Colors.DIM}  (输入\"继续\"可恢复此任务){Colors.RESET}")
                            self._pending_input = None
                        elif result.intent == InterruptIntent.RESUME:
                            if self._cancelled_task:
                                print(f"  {Colors.DIM}→ 恢复之前的任务{Colors.RESET}")
                                self._pending_input = self._cancelled_task
                                self._cancelled_task = None
                            else:
                                print(f"  {Colors.DIM}→ 没有可恢复的任务{Colors.RESET}")
                                self._pending_input = None
                        else:
                            print(f"  {Colors.DIM}→ 补充信息{Colors.RESET}")
                            self._pending_input = f"{user_input}\n\n补充信息: {new_input}"
                    except Exception:
                        pass
                else:
                    print(f"\n  {Colors.YELLOW}● 已中断{Colors.RESET}")
        else:
            input_task.cancel()
            try:
                await input_task
            except asyncio.CancelledError:
                pass
        return self._pending_input

    async def _do_process_message(self, user_input: str):
        """实际处理用户消息的逻辑"""
        try:
            from packages.server.agents.lumos_agent import AgentEvent
            import sys
            import time
            current_tool = None
            current_tool_args = {}
            content_buffer = ""
            async for event in self.agent.stream(user_input, self.session_id):
                if event.type == "thinking":
                    pass
                elif event.type == "tool_call":
                    if content_buffer:
                        print()
                        content_buffer = ""
                    tool_info = event.data
                    if isinstance(tool_info, dict):
                        tool_name = tool_info.get("name", "unknown")
                        tool_args = tool_info.get("arguments", {})
                        if isinstance(tool_args, str):
                            import json
                            try:
                                tool_args = json.loads(tool_args)
                            except:
                                pass
                        current_tool = tool_name
                        current_tool_args = tool_args
                        if tool_name == "ask_user_question":
                            self._pause_escape_listener = True
                        display_name = get_tool_display_name(tool_name, tool_args)
                        if tool_name == "todo_write":
                            print(f"\n{Colors.CYAN}● {display_name}{Colors.RESET}")
                        else:
                            args_display = self._format_tool_args(tool_name, tool_args)
                            print(f"\n{Colors.CYAN}● {display_name}{Colors.RESET}({Colors.DIM}{args_display}{Colors.RESET})")
                    else:
                        current_tool = str(event.data)
                        current_tool_args = {}
                        display_name = get_tool_display_name(current_tool, {})
                        print(f"\n{Colors.CYAN}● {display_name}{Colors.RESET}")
                elif event.type == "tool_result":
                    result = str(event.data)
                    if current_tool == "todo_write":
                        await asyncio.sleep(0.05)
                        self._display_todo_checkboxes(current_tool_args)
                    elif current_tool == "write_file":
                        self._display_write_result(result)
                    else:
                        result_summary = self._format_tool_result(current_tool, result)
                        print(f"  {Colors.DIM}⎿  {result_summary}{Colors.RESET}")
                    if current_tool == "ask_user_question":
                        self._pause_escape_listener = False
                    if current_tool == "exit_plan_mode" and "<AWAITING_USER_APPROVAL>" in result:
                        print(f"\n{Colors.YELLOW}● 等待用户审批...{Colors.RESET}")
                        current_tool = None
                        current_tool_args = {}
                        return
                    current_tool = None
                    current_tool_args = {}
                elif event.type == "content_chunk":
                    chunk = str(event.data)
                    if content_buffer == "":
                        print(f"\n{Colors.GREEN}● {Colors.RESET}", end="", flush=True)
                    print(f"{Colors.GREEN}{chunk}{Colors.RESET}", end="", flush=True)
                    content_buffer += chunk
                elif event.type == "content":
                    content = str(event.data)
                    if content:
                        paragraphs = content.strip().split('\n\n')
                        for i, para in enumerate(paragraphs):
                            if para.strip():
                                if i > 0:
                                    print()
                                print(f"\n{Colors.GREEN}● {para.strip()}{Colors.RESET}")
                elif event.type == "error":
                    print(f"\n{Colors.RED}● 错误: {event.data}{Colors.RESET}")
            if content_buffer:
                print()
        except Exception as e:
            print(f"\n{Colors.RED}● 处理失败: {str(e)}{Colors.RESET}")
            import traceback
            print(f"  {Colors.DIM}{traceback.format_exc()}{Colors.RESET}")

    def _format_tool_args(self, tool_name: str, args: dict) -> str:
        """格式化工具参数显示"""
        if not isinstance(args, dict):
            return str(args)[:50]
        if tool_name == "read_file":
            path = args.get("file_path", "")
            limit = args.get("limit", "")
            return f"{path}, limit={limit}" if limit else path
        elif tool_name == "write_file":
            return args.get("file_path", "")
        elif tool_name == "edit_file":
            return args.get("file_path", "")
        elif tool_name == "bash":
            cmd = args.get("command", "")
            return cmd[:60] + "..." if len(cmd) > 60 else cmd
        elif tool_name == "grep":
            return f'"{args.get("pattern", "")}" {args.get("path", ".")}'
        elif tool_name == "glob":
            return args.get("pattern", "")
        elif tool_name == "ls":
            return args.get("path", ".")
        elif tool_name == "web_search":
            query = args.get("query", "")
            num = args.get("num_results", "")
            return f"{query}, num_results={num}" if num else query
        elif tool_name == "web_fetch":
            url = args.get("url", "")
            prompt = args.get("prompt", "")
            if prompt:
                return f"{url}, prompt={prompt[:30]}..."
            return url
        elif tool_name in ("browser_open", "BrowserOpen"):
            return args.get("url", "")
        elif tool_name in ("browser_snapshot", "BrowserSnapshot"):
            return f"full={args.get('full', False)}"
        elif tool_name in ("browser_click", "BrowserClick"):
            return f"ref={args.get('ref', '')}"
        elif tool_name in ("browser_type", "BrowserType"):
            text = args.get("text", "")
            return f"ref={args.get('ref', '')}, text={text[:20]}..." if len(text) > 20 else f"ref={args.get('ref', '')}, text={text}"
        else:
            parts = []
            for k, v in list(args.items())[:3]:
                v_str = str(v)
                if len(v_str) > 60:
                    v_str = v_str[:60] + "..."
                parts.append(f"{k}={v_str}")
            return ", ".join(parts)

    def _display_todo_checkboxes(self, tool_args: dict) -> None:
        """显示 TodoWrite 的 checkbox 列表"""
        if not isinstance(tool_args, dict):
            print(f"  {Colors.DIM}⎿  Updated todos{Colors.RESET}")
            return
        todos = tool_args.get("todos", [])
        if not todos:
            tasks = tool_args.get("tasks", "")
            if isinstance(tasks, str) and tasks:
                import re
                task_list = re.split(r'[;\n]', tasks)
                todos = []
                for i, t in enumerate(task_list):
                    t = t.strip()
                    if t:
                        status = "in_progress" if not todos else "pending"
                        todos.append({"content": t, "status": status})
        if not todos:
            import time
            for retry in range(3):
                try:
                    sessions_dir = Path.home() / ".lumos" / "sessions"
                    session_todo_file = sessions_dir / self.session_id / "todos.json"
                    if session_todo_file.exists():
                        import json
                        with open(session_todo_file, 'r', encoding='utf-8') as f:
                            todos = json.load(f)
                        if todos:
                            break
                    else:
                        todos_dir = Path.home() / ".lumos" / "todos"
                        todo_file = todos_dir / f"{self.session_id}.json"
                        if todo_file.exists():
                            import json
                            with open(todo_file, 'r', encoding='utf-8') as f:
                                todos = json.load(f)
                            if todos:
                                break
                    if retry < 2:
                        time.sleep(0.05)
                except Exception:
                    if retry < 2:
                        time.sleep(0.05)
        if not todos:
            print(f"  {Colors.DIM}⎿  Updated todos{Colors.RESET}")
            return
        for todo in todos:
            if isinstance(todo, dict):
                content = todo.get("content", str(todo))
                status = todo.get("status", "pending")
            else:
                content = str(todo)
                status = "pending"
            if status == "completed":
                checkbox = f"{Colors.GREEN}☑{Colors.RESET}"
            elif status == "in_progress":
                checkbox = f"{Colors.YELLOW}◐{Colors.RESET}"
            else:
                checkbox = f"{Colors.DIM}☐{Colors.RESET}"
            print(f"  {Colors.DIM}⎿{Colors.RESET}  {checkbox} {Colors.DIM}{content}{Colors.RESET}")

    def _display_write_result(self, result: str) -> None:
        """显示 Write/Update 的结果"""
        if not result:
            print(f"  {Colors.DIM}⎿  Done{Colors.RESET}")
            return
        lines = result.strip().split('\n')
        if not lines:
            print(f"  {Colors.DIM}⎿  Done{Colors.RESET}")
            return
        summary = lines[0]
        print(f"  {Colors.DIM}⎿  {summary}{Colors.RESET}")
        for line in lines[1:]:
            print(f"  {Colors.DIM}   {line}{Colors.RESET}")

    def _format_tool_result(self, tool_name: str, result: str) -> str:
        """格式化工具结果显示"""
        if not result:
            return "Done"
        result_lines = result.strip().split('\n')
        line_count = len(result_lines)
        if tool_name == "read_file":
            return f"Read {line_count} lines"
        elif tool_name == "write_file":
            return result
        elif tool_name == "edit_file":
            if "成功" in result or "success" in result.lower():
                return result_lines[0]
            return "Edited file"
        elif tool_name == "bash":
            if line_count == 0:
                return "Command completed"
            elif line_count == 1:
                return result_lines[0][:80] + ("..." if len(result_lines[0]) > 80 else "")
            else:
                return f"{result_lines[0][:60]}... (+{line_count - 1} lines)"
        elif tool_name == "grep":
            if "No matches" in result or line_count == 0:
                return "No matches found"
            return f"Found {line_count} matches"
        elif tool_name == "glob":
            return "No files found" if line_count == 0 else f"Found {line_count} files"
        elif tool_name == "ls":
            return f"Listed {line_count} items"
        else:
            if line_count == 1:
                return result_lines[0][:80] + ("..." if len(result_lines[0]) > 80 else "")
            else:
                return f"{result_lines[0][:60]}... (+{line_count - 1} lines)"

    def handle_plan_approval(self, user_input: str) -> tuple[bool, str]:
        """处理 Plan 审批响应

        检测用户输入是否是对 Plan 的审批响应（approve/yes/reject/no）。
        如果是，则执行相应的模式切换。

        Returns:
            (is_approval, continue_prompt)
        """
        if not self.agent:
            return False, ""

        # 检查当前是否在 PLAN 模式
        from packages.server.agents.mode_manager import AgentMode
        if self.agent.get_current_mode() != AgentMode.PLAN:
            return False, ""

        # 检查是否有待审批的 Plan
        from packages.server.tools.plan_tools import PlanFileManager
        plan_manager = PlanFileManager(self.session_id)
        if not plan_manager.is_pending_approval():
            return False, ""

        # 检测审批响应
        input_lower = user_input.lower().strip()
        approve_keywords = ['approve', 'yes', 'y', '是', '批准', '同意', 'ok', 'lgtm']
        reject_keywords = ['reject', 'no', 'n', '否', '拒绝', '不同意']

        if input_lower in approve_keywords:
            plan_file = plan_manager.get_current_plan_file()
            plan_content = ""
            if plan_file and plan_file.exists():
                plan_content = plan_manager.read_plan_file(plan_file)

            if plan_manager.approve_plan():
                self.agent.switch_mode(AgentMode.BUILD)
                print(f"\n  {Colors.BRIGHT_GREEN}✓ Plan 已批准！{Colors.RESET}")
                print(f"  {Colors.DIM}已切换到 BUILD 模式，开始实施...{Colors.RESET}\n")

                continue_prompt = f"""用户已批准 Plan，请立即开始实施。

Plan 文件内容：
{plan_content}

请按照 Plan 中的步骤逐一实施，使用 TodoWrite 跟踪进度。开始执行第一个步骤。"""

                return True, continue_prompt
            else:
                print(f"\n  {Colors.YELLOW}⚠ 无法批准 Plan{Colors.RESET}\n")
                return True, ""

        elif input_lower in reject_keywords:
            if plan_manager.reject_plan():
                print(f"\n  {Colors.YELLOW}✗ Plan 已拒绝{Colors.RESET}")
                print(f"  {Colors.DIM}请提供反馈或修改建议...{Colors.RESET}\n")
                return True, ""
            else:
                print(f"\n  {Colors.YELLOW}⚠ 无法拒绝 Plan{Colors.RESET}\n")
                return True, ""

        return False, ""

    def _print_separator(self):
        """打印分隔线"""
        try:
            term_width = os.get_terminal_size().columns
        except OSError:
            term_width = 80
        print(f"{Colors.DIM}{'─' * term_width}{Colors.RESET}")

    def _print_input_header(self):
        """打印输入区域头部"""
        self._print_separator()

    def _print_input_footer(self):
        """打印输入区域底部"""
        print(f"{Colors.DIM}? for shortcuts{Colors.RESET}")

    async def run(self):
        """主交互循环 - 支持任务执行时输入"""
        self.show_welcome()

        # 创建带补全功能的 session
        skill_manager = self.agent.skill_manager if self.agent else None
        session = PromptSession(completer=SlashCommandCompleter(skill_manager))

        # 输入队列和处理状态
        input_queue: asyncio.Queue[str] = asyncio.Queue()
        self._processing = False
        self._current_task_description = ""
        self._current_process_task: Optional[asyncio.Task] = None

        async def input_loop():
            """输入循环 - 持续接收用户输入"""
            while self.running:
                try:
                    if self._processing:
                        await asyncio.sleep(0.1)
                        continue

                    if not self.running:
                        break

                    if self._processing:
                        await asyncio.sleep(0.1)
                        continue

                    # 获取当前模式
                    mode = "BUILD"
                    if self.agent:
                        mode = self.agent.get_current_mode().value.upper()

                    self._print_input_header()

                    # 构建提示符
                    if self.has_rich:
                        prompt_text = f"\033[1;36m[{mode}]\033[0m ❯ "
                    else:
                        prompt_text = f"[{mode}] ❯ "

                    user_input = await session.prompt_async(ANSI(prompt_text))
                    user_input = user_input.strip()

                    if user_input:
                        await input_queue.put(user_input)
                        await asyncio.sleep(0.2)

                except KeyboardInterrupt:
                    print(f"\n  {Colors.YELLOW}⚠️  使用 /exit 退出{Colors.RESET}")
                except EOFError:
                    self.running = False
                    break
                except Exception as e:
                    pass

        async def process_loop():
            """处理循环 - 从队列获取输入并处理"""
            while self.running:
                try:
                    try:
                        user_input = await asyncio.wait_for(input_queue.get(), timeout=0.1)
                    except asyncio.TimeoutError:
                        continue

                    await self._handle_user_input(user_input, session, input_queue)

                except Exception as e:
                    print(f"  {Colors.RED}❌ 处理错误: {str(e)}{Colors.RESET}")

        # 使用 patch_stdout 确保输出显示在提示符上方
        with patch_stdout(raw=True):
            input_task = asyncio.create_task(input_loop())
            process_task = asyncio.create_task(process_loop())

            try:
                done, pending = await asyncio.wait(
                    [input_task, process_task],
                    return_when=asyncio.FIRST_COMPLETED
                )

                for task in pending:
                    task.cancel()
                    try:
                        await task
                    except asyncio.CancelledError:
                        pass

            finally:
                if self._session_created:
                    self._save_session_state(status="completed")

    async def _handle_user_input(self, user_input: str, session, input_queue: asyncio.Queue = None):
        """处理用户输入的核心逻辑"""
        # 处理命令
        is_command, pending_msg = self.handle_command(user_input)
        if is_command:
            if pending_msg:
                if not self._session_created:
                    self._create_session(pending_msg)
                self._message_count += 1
                self._current_task_description = pending_msg
                self._processing = True
                try:
                    next_input = await self.process_message(pending_msg, input_queue)
                    self._save_session_state()
                    while next_input:
                        self._message_count += 1
                        self._current_task_description = next_input
                        next_input = await self.process_message(next_input, input_queue)
                        self._save_session_state()
                finally:
                    self._processing = False
                    self._current_task_description = ""
            return

        # 处理 Plan 审批响应
        is_approval, continue_prompt = self.handle_plan_approval(user_input)
        if is_approval:
            if continue_prompt:
                self._message_count += 1
                self._current_task_description = continue_prompt
                self._processing = True
                try:
                    next_input = await self.process_message(continue_prompt, input_queue)
                    self._save_session_state()
                    while next_input:
                        self._message_count += 1
                        self._current_task_description = next_input
                        next_input = await self.process_message(next_input, input_queue)
                        self._save_session_state()
                finally:
                    self._processing = False
                    self._current_task_description = ""
            return

        # 第一条消息时创建会话
        if not self._session_created:
            self._create_session(user_input)

        self._message_count += 1

        # 处理普通消息
        self._current_task_description = user_input
        self._processing = True
        try:
            next_input = await self.process_message(user_input, input_queue)
            self._save_session_state()

            while next_input:
                self._message_count += 1
                self._current_task_description = next_input
                next_input = await self.process_message(next_input, input_queue)
                self._save_session_state()
        finally:
            self._processing = False
            self._current_task_description = ""


# ============================================================================
# 主入口
# ============================================================================

def _format_tool_args_simple(tool_name: str, args: dict) -> str:
    """格式化工具参数显示（用于非交互模式）"""
    if not isinstance(args, dict):
        return str(args)[:50]

    if tool_name == "read_file":
        path = args.get("file_path", "")
        limit = args.get("limit", "")
        if limit:
            return f"{path}, limit={limit}"
        return path
    elif tool_name == "write_file":
        return args.get("file_path", "")
    elif tool_name == "edit_file":
        return args.get("file_path", "")
    elif tool_name == "bash":
        cmd = args.get("command", "")
        if len(cmd) > 60:
            cmd = cmd[:60] + "..."
        return cmd
    elif tool_name == "grep":
        pattern = args.get("pattern", "")
        path = args.get("path", ".")
        return f'"{pattern}" {path}'
    elif tool_name == "glob":
        return args.get("pattern", "")
    elif tool_name == "ls":
        return args.get("path", ".")
    else:
        parts = []
        for k, v in list(args.items())[:3]:
            v_str = str(v)[:20]
            parts.append(f"{k}={v_str}")
        return ", ".join(parts)


def render_todo_progress(todos_dir: Path, session_id: str) -> str:
    """渲染 todo 进度条"""
    import json

    todo_file = None
    for f in todos_dir.glob("*.json"):
        if session_id in f.name or f.name.startswith("noninteractive_"):
            todo_file = f
            break

    if not todo_file or not todo_file.exists():
        return ""

    try:
        with open(todo_file, 'r', encoding='utf-8') as f:
            todos = json.load(f)
    except:
        return ""

    if not todos:
        return ""

    total = len(todos)
    completed = sum(1 for t in todos if t.get("status") == "completed")
    in_progress = sum(1 for t in todos if t.get("status") == "in_progress")

    bar_width = 20
    filled = int(bar_width * completed / total) if total > 0 else 0
    current = 1 if in_progress > 0 and filled < bar_width else 0
    empty = bar_width - filled - current

    bar = f"{Colors.BRIGHT_GREEN}{'█' * filled}{Colors.RESET}"
    if current:
        bar += f"{Colors.BRIGHT_YELLOW}{'▓'}{Colors.RESET}"
    bar += f"{Colors.DIM}{'░' * empty}{Colors.RESET}"

    current_task = ""
    for t in todos:
        if t.get("status") == "in_progress":
            current_task = t.get("activeForm", t.get("content", ""))[:30]
            break

    progress_text = f"[{bar}] {completed}/{total}"
    if current_task:
        progress_text += f" {Colors.DIM}• {current_task}{Colors.RESET}"

    return progress_text


async def handle_non_interactive_command(query: str, agent) -> bool:
    """处理非交互模式下的斜杠命令"""
    if not query.startswith("/"):
        return False

    parts = query.split()
    cmd = parts[0].lower()

    if cmd == "/skills":
        skills = agent.skill_manager.list_skills()
        if skills:
            print(f"\n{Colors.CYAN}可用的 Skills:{Colors.RESET}")
            for skill in skills:
                print(f"  • {skill.name}: {skill.metadata.description}")
        else:
            print(f"{Colors.YELLOW}没有可用的 skills{Colors.RESET}")
        return True

    elif cmd == "/skill":
        if len(parts) < 2:
            print(f"{Colors.YELLOW}用法:{Colors.RESET}")
            print(f"  /skill <name>                    - 激活指定 skill")
            print(f"  /skill install <plugin>@<marketplace> - 安装远程插件")
            print(f"  /skill uninstall <plugin>@<marketplace> - 卸载插件")
            print(f"  /skill list-installed            - 列出已安装插件")
            return True

        subcmd = parts[1].lower()

        if subcmd == "install":
            if len(parts) < 3:
                print(f"{Colors.YELLOW}用法: /skill install <plugin>@<marketplace>{Colors.RESET}")
                print(f"{Colors.DIM}示例: /skill install pdf@anthropics{Colors.RESET}")
            else:
                spec = parts[2]
                try:
                    plugin = agent.skill_manager.install_plugin(spec)
                    print(f"{Colors.GREEN}✓ 安装成功: {plugin.spec}{Colors.RESET}")
                    print(f"  Skills: {', '.join(plugin.skills)}")
                except Exception as e:
                    print(f"{Colors.RED}✗ 安装失败: {e}{Colors.RESET}")
            return True

        elif subcmd == "uninstall":
            if len(parts) < 3:
                print(f"{Colors.YELLOW}用法: /skill uninstall <plugin>@<marketplace>{Colors.RESET}")
            else:
                spec = parts[2]
                try:
                    agent.skill_manager.uninstall_plugin(spec)
                    print(f"{Colors.GREEN}✓ 卸载成功: {spec}{Colors.RESET}")
                except Exception as e:
                    print(f"{Colors.RED}✗ 卸载失败: {e}{Colors.RESET}")
            return True

        elif subcmd == "list-installed":
            plugins = agent.skill_manager.list_installed_plugins()
            if plugins:
                print(f"\n{Colors.CYAN}已安装的插件:{Colors.RESET}")
                for plugin in plugins:
                    print(f"  • {plugin.spec}")
                    print(f"    Skills: {', '.join(plugin.skills)}")
            else:
                print(f"{Colors.YELLOW}没有已安装的插件{Colors.RESET}")
            return True

        else:
            skill = agent.skill_manager.get_skill(subcmd)
            if skill:
                agent.skill_manager.activate_skill(skill)
                print(f"{Colors.GREEN}✓ 已激活 skill: {subcmd}{Colors.RESET}")
            else:
                print(f"{Colors.RED}✗ 未找到 skill: {subcmd}{Colors.RESET}")
            return True

    # 检查是否是 skill 名称作为命令（如 /pdf）
    skill_name = cmd[1:]
    skill = agent.skill_manager.get_skill(skill_name)
    if skill:
        agent.skill_manager.activate_skill(skill)
        print(f"{Colors.GREEN}✓ 已激活 skill: {skill_name}{Colors.RESET}")
        if len(parts) > 1:
            return False
        return True

    return False


async def run_non_interactive(config: dict, query: str):
    """非交互式执行单个查询"""
    import sys

    try:
        from packages.server.agents.lumos_agent import LumosAgent

        api_key = config.get("api_key")
        provider = config.get("provider", "openai")
        model = config.get("model")
        api_base = config.get("api_base_url")

        agent = LumosAgent(
            model_provider=provider,
            api_key=api_key,
            api_base=api_base,
            model_name=model or "gpt-4o",
            session_id=f"noninteractive_{os.getpid()}",
        )
    except Exception as e:
        print(f"{Colors.RED}● Agent 初始化失败: {e}{Colors.RESET}")
        sys.exit(1)

    if not agent.api_key:
        print(f"{Colors.RED}● 未配置 API Key，请运行 lumos --config{Colors.RESET}")
        sys.exit(1)

    # 处理斜杠命令
    if query.startswith("/"):
        handled = await handle_non_interactive_command(query, agent)
        if handled:
            return
        parts = query.split(maxsplit=1)
        if len(parts) > 1:
            query = parts[1]
        else:
            return

    # 执行查询
    current_tool = None
    current_tool_args = {}
    content_buffer = ""
    session_id = f"noninteractive_{os.getpid()}"
    todos_dir = Path.home() / ".lumos" / "todos"

    try:
        async for event in agent.stream(query, session_id):
            if event.type == "thinking":
                print(f"{Colors.DIM}● 思考中...{Colors.RESET}")

            elif event.type == "tool_call":
                tool_info = event.data
                if isinstance(tool_info, dict):
                    tool_name = tool_info.get("name", "unknown")
                    tool_args = tool_info.get("arguments", {})
                    if isinstance(tool_args, str):
                        import json
                        try:
                            tool_args = json.loads(tool_args)
                        except:
                            pass

                    current_tool = tool_name
                    current_tool_args = tool_args

                    display_name = get_tool_display_name(tool_name)
                    args_str = _format_tool_args_simple(tool_name, tool_args)

                    if tool_name == "todo_write":
                        print(f"{Colors.CYAN}● {display_name}{Colors.RESET}")
                    else:
                        print(f"{Colors.CYAN}● {display_name}{Colors.RESET}({Colors.DIM}{args_str}{Colors.RESET})")
                else:
                    current_tool = str(event.data)
                    current_tool_args = {}
                    display_name = get_tool_display_name(current_tool)
                    print(f"{Colors.CYAN}● {display_name}{Colors.RESET}")

            elif event.type == "tool_result":
                result = str(event.data)

                if current_tool == "todo_write":
                    progress = render_todo_progress(todos_dir, session_id)
                    if progress:
                        print(f"  {Colors.DIM}⎿{Colors.RESET}  {progress}")
                    else:
                        first_line = result.split('\n')[0]
                        print(f"  {Colors.DIM}⎿  {first_line}{Colors.RESET}")
                else:
                    result_lines = result.split('\n')
                    if len(result_lines) > 3:
                        print(f"  {Colors.DIM}⎿  {result_lines[0]}{Colors.RESET}")
                        print(f"     {Colors.DIM}… +{len(result_lines)-1} lines{Colors.RESET}")
                    elif result_lines:
                        print(f"  {Colors.DIM}⎿  {result_lines[0]}{Colors.RESET}")
                current_tool = None

            elif event.type == "content_chunk":
                chunk = str(event.data)
                if content_buffer == "":
                    print()
                sys.stdout.write(f"{Colors.GREEN}{chunk}{Colors.RESET}")
                sys.stdout.flush()
                content_buffer += chunk

            elif event.type == "content":
                content = str(event.data)
                if content:
                    print()
                    print(f"{Colors.GREEN}{content}{Colors.RESET}")

            elif event.type == "error":
                print(f"\n{Colors.RED}● 错误: {event.data}{Colors.RESET}")

        if content_buffer:
            print()

    except KeyboardInterrupt:
        print(f"\n{Colors.YELLOW}● 已中断{Colors.RESET}")
        sys.exit(130)
    except Exception as e:
        print(f"\n{Colors.RED}● 执行失败: {e}{Colors.RESET}")
        sys.exit(1)


def main():
    """主入口函数 - lumos 命令"""
    import argparse

    parser = argparse.ArgumentParser(
        prog='lumos',
        description='Lumos - AI 编程助手',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='''
示例:
  lumos                    启动交互式会话
  lumos "你的问题"         非交互式执行
  lumos -p "你的问题"      非交互式执行
  lumos --config           配置 API Key
  lumos --test             运行快速测试
        '''
    )
    parser.add_argument('query', nargs='?', help='直接执行的查询（非交互式）')
    parser.add_argument('-p', '--prompt', help='直接执行的查询（非交互式）')
    parser.add_argument('--config', action='store_true', help='配置 API Key')
    parser.add_argument('--test', action='store_true', help='运行快速测试')
    parser.add_argument('--version', action='version', version=f'Lumos v{VERSION}')
    parser.add_argument('--no-color', action='store_true', help='禁用颜色输出')
    parser.add_argument('--skip-welcome', action='store_true', help='跳过欢迎界面')

    args = parser.parse_args()

    if args.no_color:
        for attr in dir(Colors):
            if not attr.startswith('_'):
                setattr(Colors, attr, '')

    # 处理 --test 参数
    if args.test:
        print(f"  {Colors.BRIGHT_CYAN}🧪 运行快速测试...{Colors.RESET}")
        try:
            from packages.server.agents.lumos_agent import LumosAgent
            agent = LumosAgent(
                model_provider="openai",
                api_key="test",
                model_name="test",
            )
            print(f"  {Colors.BRIGHT_GREEN}✓{Colors.RESET} Agent: 模式={agent.get_current_mode().value}")
            print(f"  {Colors.BRIGHT_GREEN}✓{Colors.RESET} 工具: {list(agent.react_loop.tools.keys())}")
            print(f"  {Colors.BRIGHT_GREEN}🎉 测试通过!{Colors.RESET}")
        except Exception as e:
            print(f"  {Colors.RED}❌ 测试失败: {e}{Colors.RESET}")
            sys.exit(1)
        return

    # 处理 --config 参数
    if args.config:
        print()
        print(f"  {Colors.BRIGHT_CYAN}Lumos{Colors.RESET} - API 配置")
        print(f"  {Colors.DIM}{'─' * 40}{Colors.RESET}")

        config = get_config()
        if config.get("api_key"):
            print()
            print(f"  {Colors.BRIGHT_GREEN}✓{Colors.RESET} 当前已配置 API")
            print(f"    Provider:     {Colors.BRIGHT_WHITE}{config.get('provider', 'anthropic')}{Colors.RESET}")
            print(f"    API Base URL: {Colors.BRIGHT_WHITE}{config.get('api_base_url', 'default')}{Colors.RESET}")
            print(f"    API Key:      {Colors.DIM}{'*' * 16}...{config['api_key'][-4:]}{Colors.RESET}")
            print()
            try:
                response = input(
                    f"  {Colors.BRIGHT_CYAN}?{Colors.RESET} 是否重新配置? "
                    f"{Colors.DIM}(y/N){Colors.RESET} "
                ).strip().lower()
                if response not in ('y', 'yes', '是'):
                    return
            except (KeyboardInterrupt, EOFError):
                print()
                return

        prompt_api_key_setup()
        return

    # 处理非交互式执行
    query = args.query or args.prompt
    if query:
        if not check_and_setup_config():
            print(f"  {Colors.DIM}未配置 API Key，退出程序。{Colors.RESET}")
            return

        config = get_config()
        asyncio.run(run_non_interactive(config, query))
        return

    # 交互式模式
    config = get_config()

    if config.get("api_key"):
        cli = LumosCLI(config)
        try:
            asyncio.run(cli.run())
        except KeyboardInterrupt:
            print(f"\n\n  {Colors.YELLOW}👋 再见！{Colors.RESET}\n")
        except Exception as e:
            print(f"\n  {Colors.RED}❌ 异常: {str(e)}{Colors.RESET}")
            sys.exit(1)
    else:
        if not args.skip_welcome:
            print_welcome_screen()
            try:
                input()
            except (KeyboardInterrupt, EOFError):
                print()
                return

        if not check_and_setup_config():
            print()
            print(f"  {Colors.DIM}未配置 API Key，退出程序。{Colors.RESET}")
            print()
            return

        config = get_config()
        cli = LumosCLI(config)

        try:
            asyncio.run(cli.run())
        except KeyboardInterrupt:
            print(f"\n\n  {Colors.YELLOW}👋 再见！{Colors.RESET}\n")
        except Exception as e:
            print(f"\n  {Colors.RED}❌ 异常: {str(e)}{Colors.RESET}")
            sys.exit(1)


if __name__ == "__main__":
    main()
