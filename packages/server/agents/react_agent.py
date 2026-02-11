"""
ReAct Agent 实现

实现 ReAct（Reasoning + Acting）模式的 Agent
"""

import asyncio
import os
import random
from typing import List, Dict, Any, Optional, AsyncGenerator
from dataclasses import dataclass

from ..llm.base_llm import BaseLLM, Message, LLMResponse, ToolCall
from ..tools.base_tool import BaseTool, ToolInput, ToolOutput
from .mode_manager import AgentModeManager


@dataclass
class AgentEvent:
    """Agent 事件"""
    type: str  # thinking, tool_call, tool_result, content, error
    data: Any


class ReActAgent:
    """ReAct Agent

    实现推理（Reasoning）+ 行动（Act）的循环
    """

    def __init__(
        self,
        llm: BaseLLM,
        mode_manager: AgentModeManager,
        tools: Dict[str, BaseTool],
        system_prompt: Optional[str] = None
    ):
        self.llm = llm
        self.mode_manager = mode_manager
        self.tools = tools
        self.system_prompt = system_prompt or self._get_default_system_prompt()
        self.max_iterations = 10

    def _get_default_system_prompt(self) -> str:
        """获取默认系统提示词"""
        mode_suffix = self.mode_manager.get_mode_prompt_suffix()
        return f"""You are lumos, an AI programming assistant powered by Lumos framework.

You help developers with:
- Writing and editing code
- Debugging and fixing bugs
- Explaining code and concepts
- Project management and automation

{mode_suffix}

## Tool Use Guidelines
- ALWAYS use Read tool instead of cat/head/tail for file operations
- MUST use Grep/Glob tools instead of grep/find commands
- Edit files before creating new ones when possible
- Use absolute paths with Bash to avoid cd
"""

    async def run(
        self,
        user_input: str,
        conversation_history: Optional[List[Message]] = None
    ) -> AsyncGenerator[AgentEvent, None]:
        """运行 Agent 主循环

        Args:
            user_input: 用户输入
            conversation_history: 对话历史

        Yields:
            AgentEvent: Agent 事件
        """
        # 初始化消息列表
        messages = []
        messages.append(Message(role="system", content=self.system_prompt))

        # 添加对话历史
        if conversation_history:
            messages.extend(conversation_history)

        # 添加用户输入
        messages.append(Message(role="user", content=user_input))

        # ReAct 循环
        for iteration in range(self.max_iterations):
            try:
                # 1. 调用 LLM
                yield AgentEvent(type="thinking", data=f"Iteration {iteration + 1}/{self.max_iterations}")

                response = await self._call_llm(messages)

                # 2. 检查是否有工具调用
                if not response.tool_calls:
                    # 没有工具调用，返回最终答案
                    yield AgentEvent(type="content", data=response.content)
                    break

                # 3. 执行工具调用
                for tool_call in response.tool_calls:
                    yield AgentEvent(
                        type="tool_call",
                        data={
                            "id": tool_call.id,
                            "name": tool_call.name,
                            "arguments": tool_call.arguments,
                        },
                    )

                    # 执行工具
                    tool_result = await self._execute_tool(tool_call)

                    yield AgentEvent(type="tool_result", data=tool_result)

                    # 添加工具结果到消息历史
                    messages.append(Message(
                        role="tool",
                        content=str(tool_result.data) if tool_result.success else tool_result.error,
                        tool_call_id=tool_call.id
                    ))

            except Exception as e:
                yield AgentEvent(type="error", data=str(e))
                break

    async def _call_llm(self, messages: List[Message]) -> LLMResponse:
        """调用 LLM（带重试机制）"""
        # 准备工具定义
        tools = self._get_tool_definitions()

        # 重试配置
        max_retries = 5
        base_delay = 1.0  # 基础延迟（秒）
        max_delay = 60.0  # 最大延迟（秒）

        last_exception = None

        for attempt in range(max_retries):
            try:
                # 调用 LLM
                response = await self.llm.generate(
                    messages=messages,
                    tools=tools if tools else None
                )
                return response

            except Exception as e:
                last_exception = e
                error_str = str(e)

                # 检查是否是速率限制错误 (429)
                is_rate_limit = (
                    "429" in error_str or
                    "rate limit" in error_str.lower() or
                    "too many requests" in error_str.lower() or
                    "quota" in error_str.lower()
                )

                if is_rate_limit and attempt < max_retries - 1:
                    # 计算指数退避延迟
                    delay = min(base_delay * (2 ** attempt), max_delay)
                    # 添加随机抖动 (0.5 - 1.5 倍)
                    jitter = 0.5 + random.random()
                    actual_delay = delay * jitter

                    # 记录重试信息
                    print(f"[LLM] 速率限制，{actual_delay:.1f}秒后重试 (第{attempt + 1}/{max_retries}次)...")

                    await asyncio.sleep(actual_delay)
                    continue

                # 非速率限制错误或已达最大重试次数，直接抛出
                raise

        # 所有重试都失败
        if last_exception:
            raise last_exception
        raise RuntimeError("LLM 调用失败，已达最大重试次数")

    async def _execute_tool(self, tool_call: ToolCall) -> ToolOutput:
        """执行工具"""
        tool_name = tool_call.name

        if tool_name not in self.tools:
            return ToolOutput(
                success=False,
                error=f"工具不存在: {tool_name}"
            )

        tool = self.tools[tool_name]
        inputs = ToolInput(data=tool_call.arguments)

        try:
            result = await tool.ainvoke(inputs)
            return result
        except Exception as e:
            return ToolOutput(
                success=False,
                error=f"工具执行失败: {str(e)}"
            )

    def _get_tool_definitions(self) -> List[Dict[str, Any]]:
        """获取工具定义（用于 LLM）"""
        definitions = []

        for tool_name, tool in self.tools.items():
            # 检查工具在当前模式下是否可用
            if not self.mode_manager.is_tool_allowed(tool_name):
                continue

            definitions.append({
                "name": tool.name,
                "description": tool.description,
                "input_schema": {
                    "type": "object",
                    "properties": self._get_tool_parameters(tool),
                    "required": []
                }
            })

        return definitions

    def _get_tool_parameters(self, tool: BaseTool) -> Dict[str, Any]:
        """获取工具参数定义"""
        # 这里简化处理，实际应该从工具的定义中提取
        return {
            "command": {
                "type": "string",
                "description": "要执行的命令"
            }
        }
