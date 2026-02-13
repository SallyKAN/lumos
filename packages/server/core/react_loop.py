"""
Lumos Core — ReAct Loop

自建 ReAct (Reasoning + Acting) 循环核心。
直接调用 Anthropic/OpenAI API，处理 tool_use 响应，循环执行直到完成。
"""

import json
import logging
import traceback
from enum import Enum
from dataclasses import dataclass, field
from typing import Any, AsyncGenerator, Optional

from .tool import BaseTool
from .llm import LLMConfig, Message, ToolCall

logger = logging.getLogger(__name__)


class EventType(Enum):
    """流式事件类型"""
    TEXT = "text"
    THINKING = "thinking"
    TOOL_CALL = "tool_call"
    TOOL_RESULT = "tool_result"
    ERROR = "error"
    DONE = "done"


@dataclass
class ReActEvent:
    """ReAct 循环事件"""
    type: EventType
    content: str = ""
    tool_name: str = ""
    tool_call_id: str = ""
    tool_args: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)


class ReActLoop:
    """ReAct 循环核心

    管理工具注册、LLM 调用、tool_use 循环。
    支持 Anthropic 和 OpenAI 两种 provider。
    """

    def __init__(
        self,
        config: LLMConfig,
        system_prompt: str = "",
        max_iterations: int = 25,
    ):
        self.config = config
        self.system_prompt = system_prompt
        self.max_iterations = max_iterations
        self.tools: dict[str, BaseTool] = {}
        self.messages: list[Message] = []
        self._client = None

    def add_tool(self, tool: BaseTool) -> None:
        """注册工具"""
        self.tools[tool.name] = tool

    def add_tools(self, tools: list[BaseTool]) -> None:
        """批量注册工具"""
        for tool in tools:
            self.add_tool(tool)

    def get_tool_schemas(self) -> list[dict]:
        """获取所有工具的 schema"""
        if self.config.provider == "anthropic":
            return [t.to_anthropic_schema() for t in self.tools.values()]
        else:
            return [t.to_openai_schema() for t in self.tools.values()]

    async def execute_tool(self, name: str, arguments: dict[str, Any]) -> str:
        """执行指定工具"""
        tool = self.tools.get(name)
        if not tool:
            return f"Error: Tool '{name}' not found."
        try:
            result = await tool.execute(**arguments)
            return result if isinstance(result, str) else str(result)
        except Exception as e:
            logger.error(f"Tool '{name}' error: {e}")
            return f"Error executing tool '{name}': {e}"

    def _build_messages(self, user_input: str) -> list[Message]:
        """构建消息列表"""
        messages = list(self.messages)
        messages.append(Message.user(user_input))
        return messages

    def _get_client(self):
        """懒加载 LLM client"""
        if self._client:
            return self._client
        if self.config.provider == "anthropic":
            import anthropic
            kwargs = {"api_key": self.config.api_key, "timeout": self.config.timeout}
            if self.config.api_base:
                kwargs["base_url"] = self.config.api_base
            self._client = anthropic.AsyncAnthropic(**kwargs)
        elif self.config.provider == "openai":
            import openai
            kwargs = {"api_key": self.config.api_key, "timeout": self.config.timeout}
            if self.config.api_base:
                kwargs["base_url"] = self.config.api_base
            self._client = openai.AsyncOpenAI(**kwargs)
        else:
            raise ValueError(f"Unsupported provider: {self.config.provider}")
        return self._client

    # --- Anthropic API ---

    async def _call_anthropic(self, messages: list[Message]) -> tuple[str, list[ToolCall]]:
        """调用 Anthropic API（非流式）"""
        client = self._get_client()
        api_messages = self._to_anthropic_messages(messages)
        kwargs: dict[str, Any] = {
            "model": self.config.model,
            "max_tokens": self.config.max_tokens,
            "messages": api_messages,
        }
        if self.system_prompt:
            kwargs["system"] = self.system_prompt
        if self.tools:
            kwargs["tools"] = self.get_tool_schemas()
        if self.config.temperature is not None:
            kwargs["temperature"] = self.config.temperature

        response = await client.messages.create(**kwargs)
        return self._parse_anthropic_response(response)

    async def _stream_anthropic(self, messages: list[Message]) -> AsyncGenerator[ReActEvent, None]:
        """调用 Anthropic API（流式）"""
        client = self._get_client()
        api_messages = self._to_anthropic_messages(messages)
        kwargs: dict[str, Any] = {
            "model": self.config.model,
            "max_tokens": self.config.max_tokens,
            "messages": api_messages,
        }
        if self.system_prompt:
            kwargs["system"] = self.system_prompt
        if self.tools:
            kwargs["tools"] = self.get_tool_schemas()
        if self.config.temperature is not None:
            kwargs["temperature"] = self.config.temperature

        async with client.messages.stream(**kwargs) as stream:
            current_tool_name = ""
            current_tool_id = ""
            current_tool_json = ""
            in_tool = False

            async for event in stream:
                if event.type == "content_block_start":
                    block = event.content_block
                    if hasattr(block, "type"):
                        if block.type == "tool_use":
                            in_tool = True
                            current_tool_name = block.name
                            current_tool_id = block.id
                            current_tool_json = ""
                        elif block.type == "thinking":
                            pass  # thinking block start
                elif event.type == "content_block_delta":
                    delta = event.delta
                    if hasattr(delta, "type"):
                        if delta.type == "text_delta":
                            yield ReActEvent(type=EventType.TEXT, content=delta.text)
                        elif delta.type == "thinking_delta":
                            yield ReActEvent(type=EventType.THINKING, content=delta.thinking)
                        elif delta.type == "input_json_delta":
                            current_tool_json += delta.partial_json
                elif event.type == "content_block_stop":
                    if in_tool:
                        try:
                            args = json.loads(current_tool_json) if current_tool_json else {}
                        except json.JSONDecodeError:
                            args = {}
                        yield ReActEvent(
                            type=EventType.TOOL_CALL,
                            tool_name=current_tool_name,
                            tool_call_id=current_tool_id,
                            tool_args=args,
                        )
                        in_tool = False

    def _to_anthropic_messages(self, messages: list[Message]) -> list[dict]:
        """转换为 Anthropic API 消息格式"""
        result = []
        for msg in messages:
            if msg.role == "system":
                continue  # system prompt 单独传
            if msg.role == "assistant" and msg.tool_calls:
                content = []
                if msg.content:
                    content.append({"type": "text", "text": msg.content})
                for tc in msg.tool_calls:
                    content.append({
                        "type": "tool_use",
                        "id": tc.id,
                        "name": tc.name,
                        "input": tc.arguments,
                    })
                result.append({"role": "assistant", "content": content})
            elif msg.role == "tool":
                result.append({
                    "role": "user",
                    "content": [{
                        "type": "tool_result",
                        "tool_use_id": msg.tool_call_id,
                        "content": msg.content,
                    }],
                })
            else:
                result.append({"role": msg.role, "content": msg.content})
        return result

    def _parse_anthropic_response(self, response) -> tuple[str, list[ToolCall]]:
        """解析 Anthropic 响应"""
        text = ""
        tool_calls = []
        for block in response.content:
            if block.type == "text":
                text += block.text
            elif block.type == "tool_use":
                tool_calls.append(ToolCall(
                    id=block.id,
                    name=block.name,
                    arguments=block.input,
                ))
        return text, tool_calls

    # --- OpenAI API ---

    async def _call_openai(self, messages: list[Message]) -> tuple[str, list[ToolCall]]:
        """调用 OpenAI API（非流式）"""
        client = self._get_client()
        api_messages = self._to_openai_messages(messages)
        kwargs: dict[str, Any] = {
            "model": self.config.model,
            "messages": api_messages,
            "max_tokens": self.config.max_tokens,
        }
        if self.tools:
            kwargs["tools"] = self.get_tool_schemas()
        if self.config.temperature is not None:
            kwargs["temperature"] = self.config.temperature

        response = await client.chat.completions.create(**kwargs)
        return self._parse_openai_response(response)

    def _to_openai_messages(self, messages: list[Message]) -> list[dict]:
        """转换为 OpenAI API 消息格式"""
        result = []
        if self.system_prompt:
            result.append({"role": "system", "content": self.system_prompt})
        for msg in messages:
            if msg.role == "system":
                continue
            if msg.role == "assistant" and msg.tool_calls:
                d: dict[str, Any] = {"role": "assistant", "content": msg.content or None}
                d["tool_calls"] = [{
                    "id": tc.id,
                    "type": "function",
                    "function": {"name": tc.name, "arguments": json.dumps(tc.arguments)},
                } for tc in msg.tool_calls]
                result.append(d)
            elif msg.role == "tool":
                result.append({
                    "role": "tool",
                    "tool_call_id": msg.tool_call_id,
                    "content": msg.content,
                })
            else:
                result.append({"role": msg.role, "content": msg.content})
        return result

    def _parse_openai_response(self, response) -> tuple[str, list[ToolCall]]:
        """解析 OpenAI 响应"""
        choice = response.choices[0]
        msg = choice.message
        text = msg.content or ""
        tool_calls = []
        if msg.tool_calls:
            for tc in msg.tool_calls:
                try:
                    args = json.loads(tc.function.arguments)
                except json.JSONDecodeError:
                    args = {}
                tool_calls.append(ToolCall(
                    id=tc.id,
                    name=tc.function.name,
                    arguments=args,
                ))
        return text, tool_calls

    # --- Main Loop ---

    async def run(self, user_input: str) -> str:
        """执行 ReAct 循环（非流式），返回最终文本"""
        messages = self._build_messages(user_input)
        final_text = ""

        for i in range(self.max_iterations):
            if self.config.provider == "anthropic":
                text, tool_calls = await self._call_anthropic(messages)
            else:
                text, tool_calls = await self._call_openai(messages)

            if text:
                final_text = text

            if not tool_calls:
                # 没有工具调用，循环结束
                break

            # 记录 assistant 消息（含 tool_calls）
            messages.append(Message.assistant(text, tool_calls))

            # 执行所有工具调用
            for tc in tool_calls:
                result = await self.execute_tool(tc.name, tc.arguments)
                messages.append(Message.tool_result(tc.id, result, tc.name))

        # 保存对话历史
        self.messages = messages
        return final_text

    async def stream(self, user_input: str) -> AsyncGenerator[ReActEvent, None]:
        """执行 ReAct 循环（流式），yield 事件"""
        messages = self._build_messages(user_input)

        for i in range(self.max_iterations):
            text_parts = []
            tool_calls = []

            if self.config.provider == "anthropic":
                async for event in self._stream_anthropic(messages):
                    if event.type == EventType.TEXT:
                        text_parts.append(event.content)
                        yield event
                    elif event.type == EventType.THINKING:
                        yield event
                    elif event.type == EventType.TOOL_CALL:
                        tool_calls.append(ToolCall(
                            id=event.tool_call_id,
                            name=event.tool_name,
                            arguments=event.tool_args,
                        ))
                        yield event
            else:
                # OpenAI 非流式 fallback（OpenAI 流式 tool_call 解析较复杂，后续可扩展）
                text, tcs = await self._call_openai(messages)
                if text:
                    text_parts.append(text)
                    yield ReActEvent(type=EventType.TEXT, content=text)
                tool_calls = tcs
                for tc in tcs:
                    yield ReActEvent(
                        type=EventType.TOOL_CALL,
                        tool_name=tc.name,
                        tool_call_id=tc.id,
                        tool_args=tc.arguments,
                    )

            full_text = "".join(text_parts)

            if not tool_calls:
                yield ReActEvent(type=EventType.DONE, content=full_text)
                break

            # 记录 assistant 消息
            messages.append(Message.assistant(full_text, tool_calls))

            # 执行工具并 yield 结果
            for tc in tool_calls:
                result = await self.execute_tool(tc.name, tc.arguments)
                messages.append(Message.tool_result(tc.id, result, tc.name))
                yield ReActEvent(
                    type=EventType.TOOL_RESULT,
                    content=result,
                    tool_name=tc.name,
                    tool_call_id=tc.id,
                )
        else:
            yield ReActEvent(
                type=EventType.ERROR,
                content=f"Reached max iterations ({self.max_iterations})",
            )

        self.messages = messages
