"""
任务中断处理器

处理用户在任务执行过程中的中断请求，
根据意图分类结果执行相应的操作。
"""

import asyncio
from typing import Optional
from dataclasses import dataclass
from datetime import datetime

from ..session.session_manager import SessionManager, SessionSummary, InterruptState
from ..intent.intent_classifier import IntentClassifier, InterruptIntent


@dataclass
class InterruptAction:
    """中断操作结果"""
    type: str                           # switch/pause/cancel/supplement
    save_state: bool = False            # 是否保存状态
    message: str = ""                   # 显示给用户的消息
    new_input: Optional[str] = None     # 新的用户输入（用于 switch）
    merged_input: Optional[str] = None  # 合并后的输入（用于 supplement）


class TaskInterruptHandler:
    """任务中断处理器"""

    def __init__(
        self,
        session_manager: SessionManager,
        intent_classifier: Optional[IntentClassifier] = None
    ):
        """初始化中断处理器

        Args:
            session_manager: 会话管理器
            intent_classifier: 意图分类器（可选，默认创建新实例）
        """
        self.session_manager = session_manager
        self.intent_classifier = intent_classifier or IntentClassifier()
        self._interrupt_event = asyncio.Event()
        self._current_task: Optional[str] = None
        self._is_task_running = False

    def set_current_task(self, task_description: str):
        """设置当前正在执行的任务

        Args:
            task_description: 任务描述
        """
        self._current_task = task_description
        self._is_task_running = True

    def clear_current_task(self):
        """清除当前任务"""
        self._current_task = None
        self._is_task_running = False

    def is_task_running(self) -> bool:
        """检查是否有任务正在执行"""
        return self._is_task_running

    def get_current_task(self) -> Optional[str]:
        """获取当前任务描述"""
        return self._current_task

    async def handle_interrupt(
        self,
        user_input: str,
        current_task: str,
        session_id: str,
        use_llm: bool = True
    ) -> InterruptAction:
        """处理用户中断

        Args:
            user_input: 用户新输入
            current_task: 当前正在执行的任务描述
            session_id: 会话 ID
            use_llm: 是否使用 LLM 进行意图识别

        Returns:
            InterruptAction 包含中断操作信息
        """
        # 1. 分类意图
        intent_result = await self.intent_classifier.classify(
            current_task,
            user_input,
            use_llm=use_llm
        )

        intent = intent_result.intent

        # 2. 根据意图执行操作
        if intent == InterruptIntent.SWITCH:
            return InterruptAction(
                type="switch",
                save_state=False,
                message="切换到新任务",
                new_input=user_input
            )

        elif intent == InterruptIntent.PAUSE:
            # 保存中断状态
            await self._save_interrupt_state(session_id, current_task)
            return InterruptAction(
                type="pause",
                save_state=True,
                message="任务已暂停，使用 /resume 恢复"
            )

        elif intent == InterruptIntent.CANCEL:
            return InterruptAction(
                type="cancel",
                save_state=False,
                message="任务已取消"
            )

        else:  # SUPPLEMENT
            # 合并输入
            merged = f"{current_task}\n\n补充信息: {user_input}"
            return InterruptAction(
                type="supplement",
                save_state=False,
                message="",
                merged_input=merged
            )

    def handle_interrupt_sync(
        self,
        user_input: str,
        current_task: str,
        session_id: str
    ) -> InterruptAction:
        """同步版本的中断处理（仅使用规则匹配）

        Args:
            user_input: 用户新输入
            current_task: 当前任务描述
            session_id: 会话 ID

        Returns:
            InterruptAction
        """
        # 使用同步的规则匹配
        intent_result = self.intent_classifier.classify_sync(
            current_task,
            user_input
        )

        intent = intent_result.intent

        if intent == InterruptIntent.SWITCH:
            return InterruptAction(
                type="switch",
                save_state=False,
                message="切换到新任务",
                new_input=user_input
            )

        elif intent == InterruptIntent.PAUSE:
            # 同步保存中断状态
            self._save_interrupt_state_sync(session_id, current_task)
            return InterruptAction(
                type="pause",
                save_state=True,
                message="任务已暂停，使用 /resume 恢复"
            )

        elif intent == InterruptIntent.CANCEL:
            return InterruptAction(
                type="cancel",
                save_state=False,
                message="任务已取消"
            )

        else:  # SUPPLEMENT
            merged = f"{current_task}\n\n补充信息: {user_input}"
            return InterruptAction(
                type="supplement",
                save_state=False,
                message="",
                merged_input=merged
            )

    async def _save_interrupt_state(self, session_id: str, current_task: str):
        """保存中断状态

        Args:
            session_id: 会话 ID
            current_task: 当前任务描述
        """
        # 加载现有摘要
        _, summary, todos = self.session_manager.load_session(session_id)

        if summary is None:
            summary = SessionSummary()

        # 更新中断信息
        summary.interrupted_task = current_task
        summary.last_action = f"任务被中断: {current_task[:50]}..."

        # 查找当前进行中的 todo
        current_todo_id = None
        for todo in todos:
            if todo.status == "in_progress":
                current_todo_id = todo.id
                break

        # 创建中断状态
        interrupt_state = InterruptState(
            task_description=current_task,
            current_todo_id=current_todo_id,
            timestamp=datetime.now().isoformat()
        )

        # 保存
        self.session_manager.save_session(
            session_id,
            summary=summary
        )

        # 更新会话状态为 paused
        self.session_manager.update_status(session_id, "paused")

    def _save_interrupt_state_sync(self, session_id: str, current_task: str):
        """同步版本的保存中断状态"""
        # 加载现有摘要
        _, summary, todos = self.session_manager.load_session(session_id)

        if summary is None:
            summary = SessionSummary()

        # 更新中断信息
        summary.interrupted_task = current_task
        summary.last_action = f"任务被中断: {current_task[:50]}..."

        # 保存
        self.session_manager.save_session(
            session_id,
            summary=summary
        )

        # 更新会话状态为 paused
        self.session_manager.update_status(session_id, "paused")

    def trigger_interrupt(self):
        """触发中断事件"""
        self._interrupt_event.set()

    def clear_interrupt(self):
        """清除中断事件"""
        self._interrupt_event.clear()

    async def wait_for_interrupt(self, timeout: float = None) -> bool:
        """等待中断事件

        Args:
            timeout: 超时时间（秒）

        Returns:
            是否收到中断
        """
        try:
            if timeout:
                await asyncio.wait_for(
                    self._interrupt_event.wait(),
                    timeout=timeout
                )
            else:
                await self._interrupt_event.wait()
            return True
        except asyncio.TimeoutError:
            return False
