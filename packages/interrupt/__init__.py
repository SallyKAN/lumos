"""
中断处理模块

提供任务中断处理功能
"""

from .interrupt_handler import (
    TaskInterruptHandler,
    InterruptAction,
)

__all__ = [
    "TaskInterruptHandler",
    "InterruptAction",
]
