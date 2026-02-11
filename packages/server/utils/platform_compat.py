"""
平台兼容性模块

提供跨平台抽象，包括：
- 平台检测
- 文件权限管理
- 路径处理和受限路径
- 命令黑名单和阻止模式
- 终端颜色支持检测
"""

import os
import sys
from typing import List, Set
from pathlib import Path
from enum import Enum


class Platform(Enum):
    """支持的平台"""
    WINDOWS = "windows"
    LINUX = "linux"
    MACOS = "macos"
    UNKNOWN = "unknown"


def get_current_platform() -> Platform:
    """检测当前操作系统平台

    Returns:
        Platform 枚举值
    """
    if sys.platform == "win32":
        return Platform.WINDOWS
    elif sys.platform == "darwin":
        return Platform.MACOS
    elif sys.platform.startswith("linux"):
        return Platform.LINUX
    return Platform.UNKNOWN


def is_windows() -> bool:
    """检查是否运行在 Windows 上"""
    return get_current_platform() == Platform.WINDOWS


def is_unix() -> bool:
    """检查是否运行在 Unix-like 系统上（Linux/macOS）"""
    return get_current_platform() in (Platform.LINUX, Platform.MACOS)


def set_file_permissions(file_path: Path, mode: int = 0o600) -> bool:
    """跨平台设置文件权限

    在 Unix 上：使用 os.chmod 设置指定的权限模式
    在 Windows 上：使用 icacls 限制访问权限仅当前用户

    Args:
        file_path: 文件路径
        mode: Unix 权限模式（默认 0o600，仅所有者可读写）

    Returns:
        成功返回 True，失败返回 False
    """
    try:
        file_path = Path(file_path)
        if not file_path.exists():
            return False

        if is_windows():
            # Windows: 使用 icacls 设置权限
            import subprocess
            username = os.environ.get("USERNAME", "")
            if username:
                # 禁用继承并移除所有权限
                subprocess.run(
                    ["icacls", str(file_path), "/inheritance:r"],
                    capture_output=True, check=False
                )
                # 仅授予当前用户完全控制权限
                subprocess.run(
                    ["icacls", str(file_path), "/grant:r", f"{username}:F"],
                    capture_output=True, check=False
                )
            return True
        else:
            # Unix: 使用标准 chmod
            os.chmod(file_path, mode)
            return True
    except Exception:
        # 静默失败 - 权限设置是尽力而为
        return False


def get_restricted_paths() -> List[str]:
    """获取平台特定的受限路径

    Returns:
        不应被修改的路径列表
    """
    if is_windows():
        return [
            "C:\\Windows",
            "C:\\Windows\\System32",
            "C:\\Program Files",
            "C:\\Program Files (x86)",
        ]
    else:
        return [
            "/etc",
            "/usr/bin",
            "/usr/sbin",
            "/usr/local/bin",
            "/bin",
            "/sbin",
            "/boot",
            "/sys",
            "/proc",
        ]


def is_restricted_path(path: str) -> bool:
    """检查路径是否在受限路径列表中

    Args:
        path: 要检查的路径

    Returns:
        如果路径受限返回 True
    """
    if not path:
        return False

    restricted = get_restricted_paths()
    normalized_path = os.path.normpath(os.path.expandvars(os.path.expanduser(path)))

    for restricted_path in restricted:
        # 在 Windows 上展开环境变量
        expanded = os.path.expandvars(restricted_path)
        normalized_restricted = os.path.normpath(expanded)

        # Windows 路径不区分大小写
        if is_windows():
            if normalized_path.lower().startswith(normalized_restricted.lower()):
                return True
        else:
            if normalized_path.startswith(normalized_restricted):
                return True
    return False


def get_blacklisted_commands() -> List[str]:
    """获取平台特定的黑名单命令

    这些命令无论在什么模式下都绝对禁止执行。

    Returns:
        危险命令模式列表
    """
    common = [
        ":(){:|:&};:",  # fork bomb (bash)
    ]

    if is_windows():
        return common + [
            "format ",
            "del /s /q C:\\",
            "rd /s /q C:\\",
            "rmdir /s /q C:\\",
            "diskpart",
            "bcdedit",
            "reg delete HKLM",
            "reg delete HKCR",
            "shutdown /s",
            "shutdown /r",
        ]
    else:
        return common + [
            "rm -rf /",
            "rm -rf /*",
            "mkfs",
            "dd if=/dev/zero",
            "chmod -R 777 /",
            "shutdown",
            "reboot",
            "halt",
            "init 0",
            "init 6",
        ]


def get_plan_mode_blocked_patterns() -> List[str]:
    """获取 PLAN 模式（只读模式）下阻止的命令模式

    Returns:
        修改系统状态的命令模式列表
    """
    common = [
        "git add", "git commit", "git push",
        "pip install", "npm install", "yarn add",
        "> ", ">> ",  # 重定向
    ]

    if is_windows():
        return common + [
            # 文件操作
            "del ", "erase ",
            "copy ", "xcopy ", "robocopy ",
            "move ", "ren ", "rename ",
            "mkdir ", "md ",
            "rmdir ", "rd ",
            # 属性更改
            "attrib ",
            "icacls ", "cacls ",
            "takeown ",
            # 注册表
            "reg add", "reg delete", "reg import",
            # 服务
            "sc create", "sc delete", "sc config",
            "net start", "net stop",
        ]
    else:
        return common + [
            # 文件操作
            "rm ", "mv ", "cp ",
            "mkdir ", "rmdir ", "touch ",
            # 权限更改
            "chmod ", "chown ", "chgrp ",
            # 包管理器
            "apt ", "yum ", "dnf ", "pacman ",
            "brew install", "brew uninstall",
        ]


def get_plan_mode_blocked_script_patterns() -> List[str]:
    """获取 PLAN 模式下阻止的脚本执行模式

    这些模式防止通过内联脚本绕过限制。

    Returns:
        脚本执行模式列表
    """
    common = [
        "python3 -c", "python -c", "python3 <<", "python <<",
        "node -e", "node <<",
        "ruby -e", "ruby <<",
        "perl -e", "perl <<",
    ]

    if is_windows():
        return common + [
            "cmd /c", "cmd.exe /c",
            "powershell -c", "powershell.exe -c",
            "powershell -Command", "powershell.exe -Command",
            "pwsh -c", "pwsh.exe -c",
            "wscript ", "cscript ",
        ]
    else:
        return common + [
            "bash -c", "sh -c",
            "zsh -c", "fish -c",
            "eval ",
        ]


def get_mode_blocked_commands() -> Set[str]:
    """获取 PLAN/REVIEW 模式下阻止的命令

    Returns:
        被阻止的命令名称集合
    """
    common = {"dd", "mkfs", "format", "git commit"}

    if is_windows():
        return common | {
            "del", "erase", "copy", "xcopy", "move", "ren",
            "mkdir", "md", "rmdir", "rd",
            "attrib", "icacls", "cacls", "takeown",
            "reg", "sc", "net",
        }
    else:
        return common | {
            "rm", "mv", "cp", "chmod", "chown", "chgrp",
            "mkdir", "rmdir", "touch",
        }


def supports_ansi_colors() -> bool:
    """检查终端是否支持 ANSI 颜色代码

    Returns:
        如果支持 ANSI 颜色返回 True
    """
    # 检查是否显式禁用
    if os.environ.get("NO_COLOR"):
        return False

    # 检查是否显式启用
    if os.environ.get("FORCE_COLOR"):
        return True

    # 检查输出是否是 TTY
    if not sys.stdout.isatty():
        return False

    if is_windows():
        # Windows 10 build 14393+ 支持 ANSI
        # 检查是否使用 Windows Terminal 或其他现代终端
        return bool(
            os.environ.get("WT_SESSION") or  # Windows Terminal
            os.environ.get("TERM_PROGRAM") or  # 其他终端
            os.environ.get("ANSICON")  # ANSICON
        )
    else:
        # Unix 系统通常支持 ANSI
        return True


def enable_windows_ansi() -> bool:
    """在 Windows 上启用 ANSI 转义序列支持

    应在程序初始化早期调用。

    Returns:
        成功启用或不需要时返回 True
    """
    if not is_windows():
        return True

    try:
        import ctypes
        kernel32 = ctypes.windll.kernel32

        # 获取句柄
        stdout_handle = kernel32.GetStdHandle(-11)  # STD_OUTPUT_HANDLE
        stderr_handle = kernel32.GetStdHandle(-12)  # STD_ERROR_HANDLE

        # 启用虚拟终端处理
        mode = ctypes.c_ulong()
        for handle in [stdout_handle, stderr_handle]:
            kernel32.GetConsoleMode(handle, ctypes.byref(mode))
            # ENABLE_VIRTUAL_TERMINAL_PROCESSING = 0x0004
            kernel32.SetConsoleMode(handle, mode.value | 0x0004)

        return True
    except Exception:
        return False


def normalize_path(path: str) -> str:
    """为当前平台规范化路径

    Args:
        path: 路径字符串（可能使用 / 或 \\ 分隔符）

    Returns:
        当前平台的规范化路径
    """
    return os.path.normpath(path)


def is_absolute_path(path: str) -> bool:
    """检查路径是否是当前平台的绝对路径

    Args:
        path: 要检查的路径

    Returns:
        如果路径是绝对路径返回 True
    """
    if is_windows():
        # Windows: 检查驱动器号或 UNC 路径
        return bool(
            (len(path) >= 2 and path[1] == ':') or
            path.startswith('\\\\') or
            path.startswith('//')
        )
    else:
        return path.startswith('/')
