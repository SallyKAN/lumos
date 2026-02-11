"""
用户交互工具实现

提供 AskUserQuestion 工具，允许 Agent 向用户提问以澄清需求
"""

import os
import asyncio
import json
from typing import List, Optional, Dict, Any
from dataclasses import dataclass, field, asdict
from ..core.tool import Tool, ToolInfo, Parameters, Param

from ..agents.mode_manager import AgentModeManager


# ==================== 数据模型 ====================

@dataclass
class QuestionOption:
    """问题选项"""
    label: str
    description: str = ""


@dataclass
class Question:
    """问题定义"""
    question: str
    header: str
    options: List[QuestionOption]
    multi_select: bool = False


@dataclass
class UserAnswer:
    """用户回答"""
    question_index: int
    selected_options: List[str]
    custom_input: Optional[str] = None


# ==================== 问题回调接口 ====================

class QuestionCallback:
    """问题回调接口

    用于在 CLI 或其他界面中显示问题并获取用户输入
    """

    async def ask_questions(self, questions: List[Question]) -> List[UserAnswer]:
        """向用户提问并获取回答

        Args:
            questions: 问题列表

        Returns:
            用户回答列表
        """
        raise NotImplementedError


class DefaultQuestionCallback(QuestionCallback):
    """默认问题回调 - 使用标准输入输出"""

    async def _async_input(self, prompt: str = "") -> str:
        """异步读取用户输入

        在 asyncio 事件循环中安全地读取用户输入，
        避免阻塞事件循环。
        """
        loop = asyncio.get_event_loop()
        # 使用线程池执行同步的 input()，避免阻塞事件循环
        return await loop.run_in_executor(None, lambda: input(prompt).strip())

    async def ask_questions(self, questions: List[Question]) -> List[UserAnswer]:
        """通过标准输入输出向用户提问"""
        answers = []

        for i, q in enumerate(questions):
            print(f"\n{'='*50}")
            print(f"[{q.header}] {q.question}")
            print("-" * 50)

            # 显示选项
            for j, opt in enumerate(q.options):
                desc = f" - {opt.description}" if opt.description else ""
                print(f"  {j + 1}. {opt.label}{desc}")
            print(f"  {len(q.options) + 1}. Other (自定义输入)")

            # 获取用户输入
            if q.multi_select:
                print("\n(多选，用逗号分隔选项编号，如: 1,2,3)")

            try:
                user_input = await self._async_input("\n请选择: ")
            except EOFError:
                # 非交互模式，使用第一个选项
                user_input = "1"

            # 解析用户输入
            selected = []
            custom = None

            if user_input:
                parts = [p.strip() for p in user_input.split(",")]
                for part in parts:
                    try:
                        idx = int(part) - 1
                        if 0 <= idx < len(q.options):
                            selected.append(q.options[idx].label)
                        elif idx == len(q.options):
                            # Other 选项
                            try:
                                custom = await self._async_input("请输入自定义内容: ")
                            except EOFError:
                                custom = ""
                    except ValueError:
                        # 非数字输入，作为自定义输入
                        custom = part

            # 如果没有选择，默认选第一个
            if not selected and not custom and q.options:
                selected = [q.options[0].label]

            answers.append(UserAnswer(
                question_index=i,
                selected_options=selected,
                custom_input=custom
            ))

        return answers


# 全局 pending requests 字典: request_id -> (Event, answers, session_id)
_pending_user_answers: Dict[str, tuple] = {}


def receive_user_answer(request_id: str, answers: List[Dict[str, Any]]):
    """接收用户回答（由 WebSocket 消息处理器调用）

    Args:
        request_id: 请求 ID
        answers: 回答数据列表
    """
    global _pending_user_answers
    if request_id in _pending_user_answers:
        event, _, session_id = _pending_user_answers[request_id]
        _pending_user_answers[request_id] = (event, answers, session_id)
        event.set()


class WebSocketQuestionCallback(QuestionCallback):
    """WebSocket 问题回调 - 通过 WebSocket 向前端发送问题并等待回答"""

    def __init__(self, ws_manager, session_id: str):
        """初始化 WebSocket 问题回调

        Args:
            ws_manager: WebSocket 管理器
            session_id: 会话 ID
        """
        self.ws_manager = ws_manager
        self.session_id = session_id

    async def ask_questions(self, questions: List[Question]) -> List[UserAnswer]:
        """通过 WebSocket 向用户提问

        Args:
            questions: 问题列表

        Returns:
            用户回答列表
        """
        global _pending_user_answers
        import uuid
        from ..api.websocket.protocol import create_ask_user_question_message

        # 生成唯一请求 ID
        request_id = str(uuid.uuid4())

        # 创建事件用于等待回答
        answer_event = asyncio.Event()
        _pending_user_answers[request_id] = (answer_event, None, self.session_id)

        # 将问题转换为可序列化的格式
        questions_data = []
        for q in questions:
            options_data = [
                {"label": opt.label, "description": opt.description}
                for opt in q.options
            ]
            questions_data.append({
                "question": q.question,
                "header": q.header,
                "options": options_data,
                "multi_select": q.multi_select
            })

        # 发送问题到前端
        message = create_ask_user_question_message(
            request_id=request_id,
            questions=questions_data,
            session_id=self.session_id
        )
        await self.ws_manager.broadcast_to_session(self.session_id, message)

        # 等待用户回答（最多等待 5 分钟）
        try:
            await asyncio.wait_for(answer_event.wait(), timeout=300)
        except asyncio.TimeoutError:
            _pending_user_answers.pop(request_id, None)
            raise Exception("用户回答超时（5分钟）")

        # 获取回答
        _, answers_data, _ = _pending_user_answers.pop(
            request_id, (None, None, None)
        )

        if answers_data is None:
            raise Exception("未收到用户回答")

        # 将回答数据转换为 UserAnswer 对象
        answers = []
        for i, answer_data in enumerate(answers_data):
            answers.append(UserAnswer(
                question_index=i,
                selected_options=answer_data.get("selected_options", []),
                custom_input=answer_data.get("custom_input")
            ))

        # 如果回答数量不足，用默认值填充
        while len(answers) < len(questions):
            q = questions[len(answers)]
            default_option = q.options[0].label if q.options else ""
            answers.append(UserAnswer(
                question_index=len(answers),
                selected_options=[default_option] if default_option else [],
                custom_input=None
            ))

        return answers


# 全局问题回调
_question_callback: Optional[QuestionCallback] = None


def set_question_callback(callback: QuestionCallback):
    """设置问题回调"""
    global _question_callback
    _question_callback = callback


def get_question_callback() -> QuestionCallback:
    """获取问题回调"""
    global _question_callback
    if _question_callback is None:
        _question_callback = DefaultQuestionCallback()
    return _question_callback


# ==================== AskUserQuestion 工具 ====================

class AskUserQuestionTool(Tool):
    """向用户提问工具

    允许 Agent 在执行过程中向用户提问以澄清需求、
    获取偏好或做出决策。
    """

    def __init__(
        self,
        mode_manager: Optional[AgentModeManager] = None,
        ws_manager=None,
        session_id: Optional[str] = None
    ):
        super().__init__()
        self.mode_manager = mode_manager
        self.ws_manager = ws_manager
        self.session_id = session_id
        # 如果提供了 ws_manager 和 session_id，创建 WebSocket 回调
        if ws_manager and session_id:
            self._ws_callback = WebSocketQuestionCallback(ws_manager, session_id)
        else:
            self._ws_callback = None
        self.name = "ask_user_question"
        self.description = """向用户提问以澄清需求或获取决策。

使用场景:
- 需要澄清模糊的需求
- 需要用户在多个方案中做出选择
- 需要获取用户偏好
- 需要确认重要决策

参数:
- questions: 问题列表（JSON 格式）

问题格式:
[
  {
    "question": "你想使用哪种认证方式？",
    "header": "认证方式",
    "options": [
      {"label": "JWT", "description": "无状态，适合分布式系统"},
      {"label": "Session", "description": "有状态，适合单体应用"},
      {"label": "OAuth2", "description": "第三方登录"}
    ],
    "multiSelect": false
  }
]

注意:
- 每次最多提问 10 个问题
- 每个问题最多 8 个选项
- 用户可以选择 "Other" 提供自定义输入
"""
        self.params = [
            Param(
                name="questions",
                description="问题列表（JSON 格式）",
                param_type="string",
                required=True
            )
        ]

    def invoke(self, inputs: dict, **kwargs) -> str:
        """同步调用"""
        return asyncio.run(self.ainvoke(inputs, **kwargs))

    async def ainvoke(self, inputs: dict, **kwargs) -> str:
        """异步调用"""
        questions_str = inputs.get("questions", "")

        if not questions_str:
            return "错误: 未提供问题"

        # 解析问题
        try:
            questions_data = json.loads(questions_str)
            if not isinstance(questions_data, list):
                questions_data = [questions_data]
        except json.JSONDecodeError as e:
            return f"错误: 问题格式无效 - {str(e)}"

        # 验证问题数量
        if len(questions_data) > 10:
            return "错误: 每次最多提问 10 个问题"

        # 转换为 Question 对象
        questions = []
        for q_data in questions_data:
            if not isinstance(q_data, dict):
                continue

            question_text = q_data.get("question", "")
            header = q_data.get("header", "问题")
            options_data = q_data.get("options", [])
            multi_select = q_data.get("multiSelect", False)

            if not question_text:
                continue

            # 验证选项数量
            if len(options_data) > 8:
                options_data = options_data[:8]

            options = []
            for opt_data in options_data:
                if isinstance(opt_data, dict):
                    options.append(QuestionOption(
                        label=opt_data.get("label", ""),
                        description=opt_data.get("description", "")
                    ))
                elif isinstance(opt_data, str):
                    options.append(QuestionOption(label=opt_data))

            questions.append(Question(
                question=question_text,
                header=header,
                options=options,
                multi_select=multi_select
            ))

        if not questions:
            return "错误: 没有有效的问题"

        # 获取用户回答（优先使用 WebSocket 回调）
        if self._ws_callback:
            callback = self._ws_callback
        else:
            callback = get_question_callback()
        try:
            answers = await callback.ask_questions(questions)
        except Exception as e:
            return f"错误: 获取用户回答失败 - {str(e)}"

        # 格式化回答
        result_parts = ["## 用户回答\n"]
        for i, (q, a) in enumerate(zip(questions, answers)):
            result_parts.append(f"### {q.header}")
            result_parts.append(f"**问题**: {q.question}")

            if a.selected_options:
                result_parts.append(f"**选择**: {', '.join(a.selected_options)}")
            if a.custom_input:
                result_parts.append(f"**自定义输入**: {a.custom_input}")

            result_parts.append("")

        return "\n".join(result_parts)

    def get_tool_info(self) -> ToolInfo:
        """获取工具信息"""
        return ToolInfo(
            type="function",
            name=self.name,
            description=self.description,
            parameters=Parameters(
                type="object",
                properties={
                    "questions": {
                        "type": "string",
                        "description": "问题列表（JSON 格式）"
                    }
                },
                required=["questions"]
            )
        )


# ==================== 工具工厂 ====================

def create_ask_user_question_tool(
    mode_manager: Optional[AgentModeManager] = None,
    ws_manager=None,
    session_id: Optional[str] = None
) -> Tool:
    """创建 AskUserQuestion 工具

    Args:
        mode_manager: 模式管理器
        ws_manager: WebSocket 管理器（用于 Web 模式）
        session_id: 会话 ID（用于 Web 模式）

    Returns:
        AskUserQuestion 工具实例
    """
    return AskUserQuestionTool(
        mode_manager=mode_manager,
        ws_manager=ws_manager,
        session_id=session_id
    )
