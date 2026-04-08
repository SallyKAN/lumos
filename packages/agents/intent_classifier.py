"""
意图分类器

使用 LLM（小模型）快速识别用户意图，用于任务打断场景。
支持四种意图：切换任务、暂停任务、取消任务、补充任务。
"""

import os
from enum import Enum
from typing import Dict, List, Optional
from dataclasses import dataclass


class InterruptIntent(Enum):
    """中断意图类型"""
    SWITCH = "switch"           # 切换到新任务
    PAUSE = "pause"             # 暂停当前任务
    CANCEL = "cancel"           # 取消当前任务
    SUPPLEMENT = "supplement"   # 补充当前任务
    RESUME = "resume"           # 恢复之前的任务


@dataclass
class IntentResult:
    """意图识别结果"""
    intent: InterruptIntent
    confidence: float           # 置信度 0-1
    reason: str                 # 判断理由


# 意图识别提示词模板
INTENT_CLASSIFICATION_PROMPT = """你是一个意图分类器。用户在 AI 助手执行任务时发送了新消息。
请根据当前任务和用户输入，判断用户的意图。

当前正在执行的任务: {current_task}

用户新输入: {user_input}

请判断用户意图，只返回以下四个选项之一（只返回一个英文单词）:
- SWITCH: 用户想做完全不同的事情，与当前任务无关
- PAUSE: 用户想暂停当前任务，稍后继续（如"等一下"、"暂停"、"先停一下"）
- CANCEL: 用户不想继续当前任务了（如"算了"、"不用了"、"取消"）
- SUPPLEMENT: 用户在补充信息、澄清需求或提供更多上下文（如回答问题、提供细节）

判断规则:
1. 如果用户输入与当前任务完全无关，选择 SWITCH
2. 如果用户明确表示要暂停或等待，选择 PAUSE
3. 如果用户明确表示不需要或取消，选择 CANCEL
4. 如果用户在回答问题、提供额外信息或澄清，选择 SUPPLEMENT
5. 如果不确定，默认选择 SUPPLEMENT（最保守的选择）

意图:"""


class IntentClassifier:
    """意图分类器 - 使用 LLM 快速识别用户意图"""

    def __init__(self, llm_client=None):
        """初始化意图分类器

        Args:
            llm_client: LLM 客户端（可选，如果不提供则使用规则匹配）
        """
        self.llm_client = llm_client

        # 关键词规则（作为 LLM 的后备方案）
        self._pause_keywords = [
            "暂停", "等一下", "等等", "先停", "停一下", "pause", "wait",
            "稍等", "先别", "hold on", "stop"
        ]
        self._cancel_keywords = [
            "取消", "算了", "不用了", "不要了", "cancel", "nevermind",
            "forget it", "不做了", "放弃"
        ]
        self._resume_keywords = [
            "继续", "恢复", "接着", "继续做", "resume", "continue",
            "go on", "接着做", "继续吧"
        ]
        self._switch_indicators = [
            "帮我", "请", "能不能", "可以", "我想", "我要", "先",
            "help me", "please", "can you", "could you", "查", "搜索"
        ]

    async def classify(
        self,
        current_task: str,
        user_input: str,
        use_llm: bool = True,
        conversation_history: Optional[List[Dict[str, str]]] = None
    ) -> IntentResult:
        """分类用户意图

        Args:
            current_task: 当前正在执行的任务描述
            user_input: 用户新输入
            use_llm: 是否使用 LLM（默认 True）
            conversation_history: 对话历史（可选）
                格式: [{"role": "user/assistant", "content": "..."}]

        Returns:
            IntentResult 包含意图类型、置信度和理由
        """
        user_input_lower = user_input.lower().strip()

        # 1. 首先尝试规则匹配（快速路径）
        rule_result = self._rule_based_classify(
            user_input_lower, current_task, conversation_history
        )
        if rule_result and rule_result.confidence >= 0.9:
            return rule_result

        # 2. 如果有 LLM 客户端且启用，使用 LLM 分类
        if use_llm and self.llm_client:
            try:
                llm_result = await self._llm_classify(
                    current_task, user_input, conversation_history
                )
                if llm_result:
                    return llm_result
            except Exception:
                pass  # LLM 失败，回退到规则

        # 3. 回退到规则结果或默认 SUPPLEMENT
        if rule_result:
            return rule_result

        return IntentResult(
            intent=InterruptIntent.SUPPLEMENT,
            confidence=0.5,
            reason="无法确定意图，默认为补充信息"
        )

    def _rule_based_classify(
        self,
        user_input_lower: str,
        current_task: str,
        conversation_history: Optional[List[Dict[str, str]]] = None
    ) -> Optional[IntentResult]:
        """基于规则的意图分类

        Args:
            user_input_lower: 小写的用户输入
            current_task: 当前任务
            conversation_history: 对话历史（可选，用于上下文判断）

        Returns:
            IntentResult 或 None
        """
        # 首先检查是否同时包含取消/放弃词和新任务请求
        # 例如: "算了，先帮我查下天气" -> 应该是 SWITCH 而非 CANCEL
        has_cancel_keyword = any(
            kw in user_input_lower for kw in self._cancel_keywords
        )
        has_switch_indicator = any(
            ind in user_input_lower for ind in self._switch_indicators
        )

        # 如果既有取消词又有新任务指示词，优先判断为 SWITCH
        if has_cancel_keyword and has_switch_indicator:
            # 进一步验证：检查是否真的是新任务
            current_task_lower = current_task.lower()
            current_words = set(current_task_lower.split())
            input_words = set(user_input_lower.split())
            common_words = current_words & input_words
            # 过滤掉常见词和停用词
            stop_words = {
                "的", "是", "在", "和", "了", "我", "你", "他",
                "a", "the", "is", "to", "帮我", "请", "先",
                "帮", "给", "查", "搜索", "找"
            }
            common_words -= stop_words

            if len(common_words) < 2:
                return IntentResult(
                    intent=InterruptIntent.SWITCH,
                    confidence=0.95,
                    reason="检测到取消当前任务并请求新任务"
                )

        # 检查暂停关键词
        for keyword in self._pause_keywords:
            if keyword in user_input_lower:
                return IntentResult(
                    intent=InterruptIntent.PAUSE,
                    confidence=0.95,
                    reason=f"检测到暂停关键词: {keyword}"
                )

        # 检查取消关键词（纯取消，不带新任务）
        if has_cancel_keyword and not has_switch_indicator:
            for keyword in self._cancel_keywords:
                if keyword in user_input_lower:
                    return IntentResult(
                        intent=InterruptIntent.CANCEL,
                        confidence=0.95,
                        reason=f"检测到取消关键词: {keyword}"
                    )

        # 检查恢复关键词
        for keyword in self._resume_keywords:
            if keyword in user_input_lower:
                return IntentResult(
                    intent=InterruptIntent.RESUME,
                    confidence=0.95,
                    reason=f"检测到恢复关键词: {keyword}"
                )

        # 检查是否是新任务请求
        # 如果输入包含任务指示词，可能是切换任务
        if has_switch_indicator:
            # 检查是否与当前任务相关
            current_task_lower = current_task.lower()
            current_words = set(current_task_lower.split())
            input_words = set(user_input_lower.split())
            common_words = current_words & input_words
            # 过滤掉常见词
            stop_words = {
                "的", "是", "在", "和", "了", "我", "你", "他",
                "a", "the", "is", "to", "帮我", "请", "先",
                "帮", "给", "查", "搜索", "找"
            }
            common_words -= stop_words

            if len(common_words) < 2:
                return IntentResult(
                    intent=InterruptIntent.SWITCH,
                    confidence=0.8,
                    reason="检测到新任务请求，与当前任务关联度低"
                )

        # 短输入通常是补充信息
        if len(user_input_lower) < 50:
            return IntentResult(
                intent=InterruptIntent.SUPPLEMENT,
                confidence=0.6,
                reason="短输入，可能是补充信息或回答"
            )

        return None

    async def _llm_classify(
        self,
        current_task: str,
        user_input: str,
        conversation_history: Optional[List[Dict[str, str]]] = None
    ) -> Optional[IntentResult]:
        """使用 LLM 进行意图分类

        Args:
            current_task: 当前任务
            user_input: 用户输入
            conversation_history: 对话历史（可选，用于上下文判断）

        Returns:
            IntentResult 或 None
        """
        if not self.llm_client:
            return None

        # 构建带历史上下文的提示词
        history_context = ""
        if conversation_history:
            recent_history = conversation_history[-6:]  # 最近 3 轮对话
            history_lines = []
            for msg in recent_history:
                role = "用户" if msg.get("role") == "user" else "助手"
                content = msg.get("content", "")[:100]  # 截断过长内容
                history_lines.append(f"{role}: {content}")
            if history_lines:
                history_context = "\n最近对话历史:\n" + "\n".join(history_lines)

        prompt = INTENT_CLASSIFICATION_PROMPT.format(
            current_task=current_task,
            user_input=user_input
        ) + history_context

        try:
            # 调用 LLM
            response = await self.llm_client.complete(prompt, max_tokens=10)
            response_text = response.strip().upper()

            # 解析响应
            intent_map = {
                "SWITCH": InterruptIntent.SWITCH,
                "PAUSE": InterruptIntent.PAUSE,
                "CANCEL": InterruptIntent.CANCEL,
                "SUPPLEMENT": InterruptIntent.SUPPLEMENT
            }

            for key, intent in intent_map.items():
                if key in response_text:
                    return IntentResult(
                        intent=intent,
                        confidence=0.85,
                        reason=f"LLM 判断为 {key}"
                    )

        except Exception:
            pass

        return None

    def classify_sync(
        self,
        current_task: str,
        user_input: str
    ) -> IntentResult:
        """同步版本的意图分类（仅使用规则）

        Args:
            current_task: 当前任务
            user_input: 用户输入

        Returns:
            IntentResult
        """
        user_input_lower = user_input.lower().strip()
        result = self._rule_based_classify(user_input_lower, current_task)

        if result:
            return result

        return IntentResult(
            intent=InterruptIntent.SUPPLEMENT,
            confidence=0.5,
            reason="无法确定意图，默认为补充信息"
        )
