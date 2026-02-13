"""
LLM 提供商抽象层

支持多个 LLM 提供商（Anthropic、OpenAI 等）
"""

from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional, AsyncGenerator
from dataclasses import dataclass
from enum import Enum
import asyncio


class LLMProvider(Enum):
    """LLM 提供商枚举"""
    ANTHROPIC = "anthropic"
    OPENAI = "openai"
    ZHIPU = "zhipu"  # 智谱 GLM
    OPENROUTER = "openrouter"  # OpenRouter


@dataclass
class Message:
    """消息基类"""
    role: str  # system, user, assistant, tool
    content: str
    tool_calls: Optional[List[Dict[str, Any]]] = None
    tool_call_id: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None


@dataclass
class ToolCall:
    """工具调用"""
    id: str
    name: str
    arguments: Dict[str, Any]


@dataclass
class LLMResponse:
    """LLM 响应"""
    content: str
    tool_calls: List[ToolCall]
    model: str
    usage: Dict[str, int]
    finish_reason: str


class BaseLLM(ABC):
    """LLM 基类

    所有 LLM 提供商的抽象接口
    """

    def __init__(
        self,
        api_key: str,
        model: str,
        temperature: float = 0.7,
        max_tokens: int = 8192
    ):
        self.api_key = api_key
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens

    @abstractmethod
    async def generate(
        self,
        messages: List[Message],
        tools: Optional[List[Dict[str, Any]]] = None,
        **kwargs
    ) -> LLMResponse:
        """生成响应

        Args:
            messages: 消息列表
            tools: 可用的工具列表
            **kwargs: 额外参数

        Returns:
            LLMResponse: LLM 响应
        """
        raise NotImplementedError

    @abstractmethod
    async def generate_stream(
        self,
        messages: List[Message],
        tools: Optional[List[Dict[str, Any]]] = None,
        **kwargs
    ) -> AsyncGenerator[str, None]:
        """流式生成响应

        Args:
            messages: 消息列表
            tools: 可用的工具列表
            **kwargs: 额外参数

        Yields:
            str: 响应内容片段
        """
        raise NotImplementedError


class AnthropicLLM(BaseLLM):
    """Anthropic Claude LLM 实现"""

    def __init__(
        self,
        api_key: str,
        model: str = "claude-sonnet-4-5-20250929",
        temperature: float = 0.7,
        max_tokens: int = 8192
    ):
        super().__init__(api_key, model, temperature, max_tokens)
        try:
            import anthropic
            self.client = anthropic.AsyncAnthropic(api_key=api_key)
        except ImportError:
            raise ImportError("请安装 anthropic 库: pip install anthropic")

    async def generate(
        self,
        messages: List[Message],
        tools: Optional[List[Dict[str, Any]]] = None,
        **kwargs
    ) -> LLMResponse:
        """生成响应"""
        # 转换消息格式
        anthropic_messages = []
        system_message = None

        for msg in messages:
            if msg.role == "system":
                system_message = msg.content
            else:
                anthropic_messages.append({
                    "role": msg.role,
                    "content": msg.content
                })

        # 调用 API
        if tools:
            # 有工具调用
            response = await self.client.messages.create(
                model=self.model,
                system=system_message,
                messages=anthropic_messages,
                tools=tools,
                temperature=self.temperature,
                max_tokens=self.max_tokens,
                **kwargs
            )
        else:
            # 普通对话
            response = await self.client.messages.create(
                model=self.model,
                system=system_message,
                messages=anthropic_messages,
                temperature=self.temperature,
                max_tokens=self.max_tokens,
                **kwargs
            )

        # 解析响应
        content = response.content[0].text if response.content else ""
        tool_calls = []

        if response.stop_reason == "tool_use":
            for block in response.content:
                if block.type == "tool_use":
                    tool_calls.append(ToolCall(
                        id=str(block.id),
                        name=block.name,
                        arguments=block.input
                    ))

        return LLMResponse(
            content=content,
            tool_calls=tool_calls,
            model=response.model,
            usage={
                "input_tokens": response.usage.input_tokens,
                "output_tokens": response.usage.output_tokens
            },
            finish_reason=response.stop_reason
        )

    async def generate_stream(
        self,
        messages: List[Message],
        tools: Optional[List[Dict[str, Any]]] = None,
        **kwargs
    ) -> AsyncGenerator[str, None]:
        """流式生成"""
        anthropic_messages = []
        system_message = None

        for msg in messages:
            if msg.role == "system":
                system_message = msg.content
            else:
                anthropic_messages.append({
                    "role": msg.role,
                    "content": msg.content
                })

        async with self.client.messages.stream(
            model=self.model,
            system=system_message,
            messages=anthropic_messages,
            temperature=self.temperature,
            max_tokens=self.max_tokens,
            **kwargs
        ) as stream:
            async for text in stream.text_stream:
                yield text


class OpenAILLM(BaseLLM):
    """OpenAI GPT LLM 实现"""

    def __init__(
        self,
        api_key: str,
        model: str = "gpt-4o",
        temperature: float = 0.7,
        max_tokens: int = 8192
    ):
        super().__init__(api_key, model, temperature, max_tokens)
        try:
            import openai
            self.client = openai.AsyncOpenAI(api_key=api_key)
        except ImportError:
            raise ImportError("请安装 openai 库: pip install openai")

    async def generate(
        self,
        messages: List[Message],
        tools: Optional[List[Dict[str, Any]]] = None,
        **kwargs
    ) -> LLMResponse:
        """生成响应"""
        # 转换消息格式
        openai_messages = [{"role": msg.role, "content": msg.content} for msg in messages]

        # 调用 API
        if tools:
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=openai_messages,
                tools=tools,
                temperature=self.temperature,
                max_tokens=self.max_tokens,
                **kwargs
            )
        else:
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=openai_messages,
                temperature=self.temperature,
                max_tokens=self.max_tokens,
                **kwargs
            )

        # 解析响应
        message = response.choices[0].message
        content = message.content or ""
        tool_calls = []

        if message.tool_calls:
            for tool_call in message.tool_calls:
                import json
                tool_calls.append(ToolCall(
                    id=tool_call.id,
                    name=tool_call.function.name,
                    arguments=json.loads(tool_call.function.arguments)
                ))

        return LLMResponse(
            content=content,
            tool_calls=tool_calls,
            model=response.model,
            usage={
                "input_tokens": response.usage.prompt_tokens,
                "output_tokens": response.usage.completion_tokens
            },
            finish_reason=response.choices[0].finish_reason
        )

    async def generate_stream(
        self,
        messages: List[Message],
        tools: Optional[List[Dict[str, Any]]] = None,
        **kwargs
    ) -> AsyncGenerator[str, None]:
        """流式生成"""
        openai_messages = [{"role": msg.role, "content": msg.content} for msg in messages]

        stream = await self.client.chat.completions.create(
            model=self.model,
            messages=openai_messages,
            temperature=self.temperature,
            max_tokens=self.max_tokens,
            stream=True,
            **kwargs
        )

        async for chunk in stream:
            if chunk.choices[0].delta.content:
                yield chunk.choices[0].delta.content


class ZhiPuLLM(BaseLLM):
    """智谱 GLM LLM 实现
    
    智谱 API 兼容 OpenAI 格式，支持 GLM-4 系列模型
    API 文档: https://open.bigmodel.cn/dev/api
    """

    def __init__(
        self,
        api_key: str,
        model: str = "glm-4",
        api_base: str = "https://open.bigmodel.cn/api/paas/v4",
        temperature: float = 0.7,
        max_tokens: int = 8192
    ):
        super().__init__(api_key, model, temperature, max_tokens)
        self.api_base = api_base
        try:
            import openai
            import httpx
            
            # 创建自定义 HTTP 客户端（禁用代理）
            http_client = httpx.AsyncClient(
                timeout=httpx.Timeout(120.0, connect=30.0),
                proxy=None  # 明确禁用代理
            )
            
            self.client = openai.AsyncOpenAI(
                api_key=api_key,
                base_url=api_base,
                http_client=http_client
            )
        except ImportError:
            raise ImportError("请安装 openai 库: pip install openai")

    async def generate(
        self,
        messages: List[Message],
        tools: Optional[List[Dict[str, Any]]] = None,
        **kwargs
    ) -> LLMResponse:
        """生成响应"""
        # 转换消息格式
        zhipu_messages = [{"role": msg.role, "content": msg.content} for msg in messages]

        # 调用 API
        try:
            if tools:
                # 智谱工具调用格式
                zhipu_tools = self._convert_tools(tools)
                response = await self.client.chat.completions.create(
                    model=self.model,
                    messages=zhipu_messages,
                    tools=zhipu_tools,
                    temperature=self.temperature,
                    max_tokens=self.max_tokens,
                    **kwargs
                )
            else:
                response = await self.client.chat.completions.create(
                    model=self.model,
                    messages=zhipu_messages,
                    temperature=self.temperature,
                    max_tokens=self.max_tokens,
                    **kwargs
                )
        except Exception as e:
            # 处理错误
            raise Exception(f"智谱 API 调用失败: {str(e)}")

        # 解析响应
        message = response.choices[0].message
        content = message.content or ""
        tool_calls = []

        if hasattr(message, 'tool_calls') and message.tool_calls:
            for tool_call in message.tool_calls:
                import json
                try:
                    args = json.loads(tool_call.function.arguments)
                except:
                    args = {}
                tool_calls.append(ToolCall(
                    id=tool_call.id,
                    name=tool_call.function.name,
                    arguments=args
                ))

        return LLMResponse(
            content=content,
            tool_calls=tool_calls,
            model=response.model,
            usage={
                "input_tokens": response.usage.prompt_tokens if response.usage else 0,
                "output_tokens": response.usage.completion_tokens if response.usage else 0
            },
            finish_reason=response.choices[0].finish_reason or "stop"
        )

    async def generate_stream(
        self,
        messages: List[Message],
        tools: Optional[List[Dict[str, Any]]] = None,
        **kwargs
    ) -> AsyncGenerator[str, None]:
        """流式生成"""
        zhipu_messages = [{"role": msg.role, "content": msg.content} for msg in messages]

        try:
            stream = await self.client.chat.completions.create(
                model=self.model,
                messages=zhipu_messages,
                temperature=self.temperature,
                max_tokens=self.max_tokens,
                stream=True,
                **kwargs
            )

            async for chunk in stream:
                if chunk.choices and chunk.choices[0].delta.content:
                    yield chunk.choices[0].delta.content
        except Exception as e:
            yield f"[错误: {str(e)}]"

    def _convert_tools(self, tools: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """转换工具格式为智谱兼容格式"""
        zhipu_tools = []
        for tool in tools:
            zhipu_tool = {
                "type": "function",
                "function": {
                    "name": tool.get("name", ""),
                    "description": tool.get("description", ""),
                    "parameters": tool.get("input_schema", {})
                }
            }
            zhipu_tools.append(zhipu_tool)
        return zhipu_tools


class OpenRouterLLM(BaseLLM):
    """OpenRouter LLM 实现

    OpenRouter 提供统一的 API 访问多种模型，兼容 OpenAI 格式
    API 文档: https://openrouter.ai/docs
    """

    def __init__(
        self,
        api_key: str,
        model: str = "zhipu/glm-4-plus",
        api_base: str = "https://openrouter.ai/api/v1",
        temperature: float = 0.7,
        max_tokens: int = 8192
    ):
        super().__init__(api_key, model, temperature, max_tokens)
        self.api_base = api_base
        try:
            import openai
            import httpx

            # 使用 http_proxy/https_proxy 环境变量的代理
            # 忽略 all_proxy（socks 协议 httpx 不直接支持）
            import os
            proxy_url = os.environ.get("https_proxy") or os.environ.get(
                "http_proxy"
            )
            http_client = httpx.AsyncClient(
                timeout=httpx.Timeout(120.0, connect=30.0),
                proxy=proxy_url,
                trust_env=False  # 禁用自动读取环境变量，避免 socks:// 报错
            )

            self.client = openai.AsyncOpenAI(
                api_key=api_key,
                base_url=api_base,
                http_client=http_client,
                default_headers={
                    "HTTP-Referer": "https://github.com/lumos/lumos-code",
                    "X-Title": "Lumos"
                }
            )
        except ImportError:
            raise ImportError("请安装 openai 库: pip install openai")

    async def generate(
        self,
        messages: List[Message],
        tools: Optional[List[Dict[str, Any]]] = None,
        **kwargs
    ) -> LLMResponse:
        """生成响应"""
        openrouter_messages = [{"role": msg.role, "content": msg.content} for msg in messages]

        try:
            if tools:
                openrouter_tools = self._convert_tools(tools)
                response = await self.client.chat.completions.create(
                    model=self.model,
                    messages=openrouter_messages,
                    tools=openrouter_tools,
                    temperature=self.temperature,
                    max_tokens=self.max_tokens,
                    **kwargs
                )
            else:
                response = await self.client.chat.completions.create(
                    model=self.model,
                    messages=openrouter_messages,
                    temperature=self.temperature,
                    max_tokens=self.max_tokens,
                    **kwargs
                )
        except Exception as e:
            raise Exception(f"OpenRouter API 调用失败: {str(e)}")

        message = response.choices[0].message
        content = message.content or ""
        tool_calls = []

        if hasattr(message, 'tool_calls') and message.tool_calls:
            for tool_call in message.tool_calls:
                import json
                try:
                    args = json.loads(tool_call.function.arguments)
                except:
                    args = {}
                tool_calls.append(ToolCall(
                    id=tool_call.id,
                    name=tool_call.function.name,
                    arguments=args
                ))

        return LLMResponse(
            content=content,
            tool_calls=tool_calls,
            model=response.model,
            usage={
                "input_tokens": response.usage.prompt_tokens if response.usage else 0,
                "output_tokens": response.usage.completion_tokens if response.usage else 0
            },
            finish_reason=response.choices[0].finish_reason or "stop"
        )

    async def generate_stream(
        self,
        messages: List[Message],
        tools: Optional[List[Dict[str, Any]]] = None,
        **kwargs
    ) -> AsyncGenerator[str, None]:
        """流式生成"""
        openrouter_messages = [{"role": msg.role, "content": msg.content} for msg in messages]

        try:
            stream = await self.client.chat.completions.create(
                model=self.model,
                messages=openrouter_messages,
                temperature=self.temperature,
                max_tokens=self.max_tokens,
                stream=True,
                **kwargs
            )

            async for chunk in stream:
                if chunk.choices and chunk.choices[0].delta.content:
                    yield chunk.choices[0].delta.content
        except Exception as e:
            yield f"[错误: {str(e)}]"

    def _convert_tools(self, tools: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """转换工具格式"""
        converted = []
        for tool in tools:
            converted.append({
                "type": "function",
                "function": {
                    "name": tool.get("name", ""),
                    "description": tool.get("description", ""),
                    "parameters": tool.get("input_schema", {})
                }
            })
        return converted


def create_llm(
    provider: LLMProvider,
    api_key: str,
    model: Optional[str] = None,
    api_base: Optional[str] = None,
    **kwargs
) -> BaseLLM:
    """创建 LLM 实例

    Args:
        provider: LLM 提供商
        api_key: API 密钥
        model: 模型名称（可选）
        api_base: API Base URL（可选）
        **kwargs: 额外参数

    Returns:
        BaseLLM: LLM 实例
    """
    if provider == LLMProvider.ANTHROPIC:
        default_model = "claude-sonnet-4-5-20250929"
        return AnthropicLLM(
            api_key=api_key,
            model=model or default_model,
            **kwargs
        )
    elif provider == LLMProvider.OPENAI:
        default_model = "gpt-4o"
        return OpenAILLM(
            api_key=api_key,
            model=model or default_model,
            **kwargs
        )
    elif provider == LLMProvider.ZHIPU:
        default_model = "glm-4"
        default_api_base = "https://open.bigmodel.cn/api/paas/v4"
        return ZhiPuLLM(
            api_key=api_key,
            model=model or default_model,
            api_base=api_base or default_api_base,
            **kwargs
        )
    elif provider == LLMProvider.OPENROUTER:
        default_model = "zhipu/glm-4-plus"
        default_api_base = "https://openrouter.ai/api/v1"
        return OpenRouterLLM(
            api_key=api_key,
            model=model or default_model,
            api_base=api_base or default_api_base,
            **kwargs
        )
    else:
        raise ValueError(f"不支持的 LLM 提供商: {provider}")
