"""
意图识别模块

提供用户意图分类功能，用于任务打断场景
"""

from .intent_classifier import (
    IntentClassifier,
    InterruptIntent,
    IntentResult,
)

__all__ = [
    "IntentClassifier",
    "InterruptIntent",
    "IntentResult",
]
