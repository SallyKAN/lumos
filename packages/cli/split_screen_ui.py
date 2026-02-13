"""分屏 UI 模块

实现类似 Claude Code 的分屏界面：
- 顶部：输出区域（显示 Agent 响应、工具调用等）
- 底部：输入区域（用户可以随时输入）

使用 prompt_toolkit 的 Application 和 Layout 实现。
"""

import asyncio
import sys
from typing import Optional, Callable, Awaitable, List
from dataclasses import dataclass, field
from datetime import datetime

from prompt_toolkit import Application
from prompt_toolkit.buffer import Buffer
from prompt_toolkit.layout import Layout, HSplit, Window, ScrollablePane
from prompt_toolkit.layout.controls import FormattedTextControl
from prompt_toolkit.layout.margins import ScrollbarMargin
from prompt_toolkit.widgets import TextArea, Frame
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.keys import Keys
from prompt_toolkit.styles import Style
from prompt_toolkit.formatted_text import FormattedText
from prompt_toolkit.completion import Completer


@dataclass
class OutputLine:
    """输出行"""
    text: str
    style: str = ""  # 样式类名
    timestamp: datetime = field(default_factory=datetime.now)


class OutputBuffer:
    """输出缓冲区

    管理输出内容，支持滚动和追加。
    """

    def __init__(self, max_lines: int = 10000):
        self.lines: List[OutputLine] = []
        self.max_lines = max_lines
        self._on_update: Optional[Callable[[], None]] = None

    def append(self, text: str, style: str = ""):
        """追加一行输出"""
        # 处理多行文本
        for line in text.split('\n'):
            self.lines.append(OutputLine(text=line, style=style))

        # 限制最大行数
        if len(self.lines) > self.max_lines:
            self.lines = self.lines[-self.max_lines:]

        # 触发更新回调
        if self._on_update:
            self._on_update()

    def append_raw(self, text: str):
        """追加原始文本（不分行）"""
        if self.lines and not self.lines[-1].text.endswith('\n'):
            # 追加到最后一行
            self.lines[-1] = OutputLine(
                text=self.lines[-1].text + text,
                style=self.lines[-1].style
            )
        else:
            self.lines.append(OutputLine(text=text))

        if self._on_update:
            self._on_update()

    def clear(self):
        """清空输出"""
        self.lines.clear()
        if self._on_update:
            self._on_update()

    def get_formatted_text(self) -> FormattedText:
        """获取格式化文本用于显示"""
        result = []
        for line in self.lines:
            if line.style:
                # 在 FormattedText 中引用样式时需要 class: 前缀
                style_ref = f'class:{line.style}' if not line.style.startswith('class:') else line.style
                result.append((style_ref, line.text + '\n'))
            else:
                result.append(('', line.text + '\n'))
        return FormattedText(result)

    def get_plain_text(self) -> str:
        """获取纯文本"""
        return '\n'.join(line.text for line in self.lines)

    def set_update_callback(self, callback: Callable[[], None]):
        """设置更新回调"""
        self._on_update = callback


class SplitScreenUI:
    """分屏 UI

    实现顶部输出区域和底部输入区域的分屏界面。
    """

    def __init__(
        self,
        completer: Optional[Completer] = None,
        on_submit: Optional[Callable[[str], Awaitable[None]]] = None,
        prompt_text: str = "❯ ",
        title: str = "Lumos"
    ):
        """初始化分屏 UI

        Args:
            completer: 命令补全器
            on_submit: 提交回调函数
            prompt_text: 提示符文本
            title: 窗口标题
        """
        self.completer = completer
        self.on_submit = on_submit
        self.prompt_text = prompt_text
        self.title = title

        # 输出缓冲区
        self.output_buffer = OutputBuffer()

        # 输入区域
        self.input_buffer = Buffer(
            completer=completer,
            multiline=False,
            accept_handler=self._on_accept
        )

        # 状态
        self.running = True
        self.mode = "BUILD"
        self._pending_input: Optional[str] = None
        self._input_event = asyncio.Event()

        # 创建 UI 组件
        self._create_layout()
        self._create_keybindings()
        self._create_style()

        # 创建应用
        self.app: Optional[Application] = None

    def _create_layout(self):
        """创建布局"""
        # 输出区域控件
        self.output_control = FormattedTextControl(
            text=self._get_output_text,
            focusable=False
        )

        # 输出窗口（可滚动）
        self.output_window = Window(
            content=self.output_control,
            wrap_lines=True,
            right_margins=[ScrollbarMargin(display_arrows=True)],
        )

        # 输入区域
        self.input_field = TextArea(
            height=1,
            prompt=self._get_prompt,
            multiline=False,
            completer=self.completer,
            accept_handler=self._on_text_accept,
            focusable=True,
        )

        # 状态栏
        self.status_bar = FormattedTextControl(
            text=self._get_status_text
        )

        # 主布局：顶部输出 + 底部输入
        self.layout = Layout(
            HSplit([
                # 输出区域（占据大部分空间）
                Frame(
                    ScrollablePane(self.output_window),
                    title=self.title,
                ),
                # 状态栏
                Window(
                    content=self.status_bar,
                    height=1,
                    style='class:status-bar'
                ),
                # 输入区域
                self.input_field,
            ])
        )

    def _create_keybindings(self):
        """创建键绑定"""
        self.kb = KeyBindings()

        @self.kb.add(Keys.ControlC)
        def handle_ctrl_c(_event):
            """Ctrl+C 中断当前操作"""
            self._pending_input = None
            self._input_event.set()

        @self.kb.add(Keys.ControlD)
        def handle_ctrl_d(event):
            """Ctrl+D 退出"""
            self.running = False
            event.app.exit()

        @self.kb.add(Keys.Escape)
        def handle_escape(_event):
            """Esc 中断当前任务"""
            self.print_output("\n● 已中断", style="class:warning")
            self._pending_input = None
            self._input_event.set()

        @self.kb.add(Keys.PageUp)
        def handle_page_up(_event):
            """Page Up 向上滚动"""
            # 滚动输出区域 - 由 ScrollablePane 自动处理
            pass

        @self.kb.add(Keys.PageDown)
        def handle_page_down(_event):
            """Page Down 向下滚动"""
            # 滚动输出区域 - 由 ScrollablePane 自动处理
            pass

    def _create_style(self):
        """创建样式"""
        self.style = Style.from_dict({
            # 输出区域
            'output': '#ffffff',
            'output.tool': '#00ffff',  # 青色 - 工具调用
            'output.result': '#888888',  # 灰色 - 工具结果
            'output.content': '#00ff00',  # 绿色 - AI 响应
            'output.error': '#ff0000',  # 红色 - 错误
            'output.warning': '#ffff00',  # 黄色 - 警告

            # 状态栏
            'status-bar': 'bg:#333333 #ffffff',
            'status-bar.mode': 'bg:#00ffff #000000 bold',
            'status-bar.info': '#888888',

            # 输入区域
            'input': '#ffffff',
            'prompt': '#00ffff bold',

            # 通用样式（不带 class: 前缀）
            'tool': '#00ffff',
            'result': '#888888',
            'content': '#00ff00',
            'error': '#ff0000',
            'warning': '#ffff00',
        })

    def _get_output_text(self) -> FormattedText:
        """获取输出文本"""
        return self.output_buffer.get_formatted_text()

    def _get_prompt(self) -> FormattedText:
        """获取提示符"""
        return FormattedText([
            ('class:prompt', f'[{self.mode}] {self.prompt_text}')
        ])

    def _get_status_text(self) -> FormattedText:
        """获取状态栏文本"""
        return FormattedText([
            ('class:status-bar.mode', f' {self.mode} '),
            ('class:status-bar', ' '),
            ('class:status-bar.info', 'Esc: 中断 | Ctrl+C: 取消 | Ctrl+D: 退出'),
        ])

    def _on_accept(self, buff: Buffer) -> bool:
        """输入接受处理"""
        text = buff.text.strip()
        if text:
            self._pending_input = text
            self._input_event.set()
        buff.reset()
        return True

    def _on_text_accept(self, buff: Buffer) -> bool:
        """TextArea 输入接受处理"""
        text = buff.text.strip()
        if text:
            self._pending_input = text
            self._input_event.set()
        return True

    def print_output(self, text: str, style: str = "", end: str = "\n"):
        """打印输出到输出区域

        Args:
            text: 输出文本
            style: 样式类名
            end: 结尾字符
        """
        if end == "\n":
            self.output_buffer.append(text, style)
        else:
            self.output_buffer.append_raw(text)

        # 刷新显示
        if self.app:
            self.app.invalidate()

    def print_tool_call(self, tool_name: str, args_display: str):
        """打印工具调用"""
        self.print_output(f"● {tool_name}({args_display})", style="tool")

    def print_tool_result(self, result: str):
        """打印工具结果"""
        self.print_output(f"  ⎿  {result}", style="result")

    def print_content(self, content: str):
        """打印 AI 响应内容"""
        self.print_output(f"● {content}", style="content")

    def print_error(self, error: str):
        """打印错误"""
        self.print_output(f"● 错误: {error}", style="error")

    def print_warning(self, warning: str):
        """打印警告"""
        self.print_output(f"● {warning}", style="warning")

    def set_mode(self, mode: str):
        """设置当前模式"""
        self.mode = mode
        if self.app:
            self.app.invalidate()

    def clear_output(self):
        """清空输出"""
        self.output_buffer.clear()
        if self.app:
            self.app.invalidate()

    async def get_input(self) -> Optional[str]:
        """异步获取用户输入

        Returns:
            用户输入的文本，如果中断则返回 None
        """
        self._pending_input = None
        self._input_event.clear()

        # 等待输入事件
        await self._input_event.wait()

        return self._pending_input

    async def run_async(self):
        """异步运行 UI"""
        self.app = Application(
            layout=self.layout,
            key_bindings=self.kb,
            style=self.style,
            full_screen=True,
            mouse_support=True,
        )

        # 设置输出缓冲区更新回调
        def on_update():
            if self.app is not None:
                self.app.invalidate()
        self.output_buffer.set_update_callback(on_update)

        try:
            await self.app.run_async()
        finally:
            self.app = None

    def run(self):
        """同步运行 UI"""
        asyncio.run(self.run_async())


class SplitScreenPrinter:
    """分屏打印器

    用于重定向 print 输出到分屏 UI。
    """

    def __init__(self, ui: SplitScreenUI):
        self.ui = ui
        self._original_stdout = sys.stdout
        self._original_stderr = sys.stderr

    def write(self, text: str):
        """写入文本"""
        if text.strip():
            self.ui.print_output(text.rstrip('\n'))

    def flush(self):
        """刷新"""
        pass

    def __enter__(self):
        """进入上下文，重定向输出"""
        sys.stdout = self
        sys.stderr = self
        return self

    def __exit__(self, _exc_type, _exc_val, _exc_tb):
        """退出上下文，恢复输出"""
        sys.stdout = self._original_stdout
        sys.stderr = self._original_stderr


# 简化版分屏 UI（不使用全屏模式）
class SimpleOutputArea:
    """简化的输出区域

    使用 ANSI 转义序列实现简单的分屏效果：
    - 输出区域在上方，可滚动
    - 输入区域固定在底部
    """

    def __init__(self):
        self.lines: List[str] = []
        self.max_lines = 1000

    def append(self, text: str):
        """追加输出"""
        for line in text.split('\n'):
            self.lines.append(line)

        if len(self.lines) > self.max_lines:
            self.lines = self.lines[-self.max_lines:]

    def clear(self):
        """清空"""
        self.lines.clear()

    def render(self) -> str:
        """渲染输出"""
        return '\n'.join(self.lines)
