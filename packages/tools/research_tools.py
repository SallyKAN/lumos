"""
调研工具集

提供 Research 子代理工具，支持并发执行多个调研任务
"""

import os
import asyncio
from typing import Optional, List, Dict, Any
from dataclasses import dataclass, field
from enum import Enum
from ..core.tool import Tool, ToolInfo, Parameters, Param

from ..agents.mode_manager import AgentModeManager


# ==================== 调研任务状态 ====================

class ResearchStatus(Enum):
    """调研任务状态"""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class ResearchTask:
    """调研任务"""
    topic: str
    description: str
    status: ResearchStatus = ResearchStatus.PENDING
    result: str = ""
    error: str = ""


@dataclass
class ResearchResult:
    """调研结果"""
    topic: str
    summary: str
    key_points: List[str] = field(default_factory=list)
    sources: List[Dict[str, str]] = field(default_factory=list)
    raw_data: str = ""


# ==================== ResearchAgentTool ====================

class ResearchAgentTool(Tool):
    """调研子代理工具

    启动调研子代理执行单个调研任务。
    具备网络搜索、网页抓取、浏览器自动化能力。
    """

    def __init__(
        self,
        mode_manager: Optional[AgentModeManager] = None,
        session_id: Optional[str] = None,
        model_provider: str = "openai",
        api_key: Optional[str] = None,
        api_base: Optional[str] = None,
        model_name: str = "gpt-4o"
    ):
        super().__init__()
        self.mode_manager = mode_manager
        self.session_id = session_id
        self.model_provider = model_provider
        self.api_key = api_key
        self.api_base = api_base
        self.model_name = model_name

        self.name = "research_agent"
        self.description = """启动调研子代理执行调研任务。

调研子代理具备以下能力:
- 网络搜索 (WebSearch): 搜索相关信息
- 网页抓取 (WebFetch): 获取网页详细内容
- 浏览器自动化 (Browser): 处理动态网页

使用场景:
- 调研竞品、技术、市场等信息
- 收集和分析网络资料
- 生成调研报告

参数:
- topic: 调研主题（必需）
- description: 详细调研要求（必需）
- output_format: 输出格式 (summary/detailed/table)

示例:
- topic: "Cursor AI 编程助手"
- description: "分析 Cursor 的核心功能、定价策略、技术特点"
- output_format: "detailed"
"""
        self.params = [
            Param(
                name="topic",
                description="调研主题",
                param_type="string",
                required=True
            ),
            Param(
                name="description",
                description="详细调研要求",
                param_type="string",
                required=True
            ),
            Param(
                name="output_format",
                description="输出格式: summary(摘要), detailed(详细), table(表格)",
                param_type="string",
                required=False
            ),
        ]

    def invoke(self, inputs: dict, **kwargs) -> str:
        """同步调用"""
        return asyncio.run(self.ainvoke(inputs, **kwargs))

    async def ainvoke(self, inputs: dict, **kwargs) -> str:  # noqa: ARG002
        """异步调用"""
        topic = inputs.get("topic", "").strip()
        description = inputs.get("description", "").strip()
        output_format = inputs.get("output_format", "detailed")

        if not topic:
            return "错误: 未指定调研主题"
        if not description:
            return "错误: 未指定调研要求"

        # 执行调研
        try:
            result = await self._execute_research(topic, description, output_format)
            return result
        except Exception as e:
            return f"错误: 调研执行失败 - {str(e)}"

    async def _execute_research(
        self,
        topic: str,
        description: str,
        output_format: str
    ) -> str:
        """执行调研任务

        使用 LLM + 工具组合完成调研
        """
        # 构建调研系统提示词
        system_prompt = f"""你是一个专业的调研分析师。你的任务是对指定主题进行深入调研。

## 调研主题
{topic}

## 调研要求
{description}

## 输出格式
{output_format}

## 调研流程
1. 使用 web_search 搜索相关信息
2. 使用 web_fetch 获取重要网页的详细内容
3. 如果需要处理动态网页，使用 browser_* 工具
4. 整理和分析收集到的信息
5. 按照指定格式输出调研结果

## 输出要求
- summary: 简洁的摘要（200-300字）
- detailed: 详细报告，包含背景、分析、结论
- table: 结构化表格形式

请开始调研。
"""

        # 尝试使用 lumos SDK 创建子代理
        try:
            from ..agents.lumos_agent import LumosCodeAgent

            # 创建调研子代理
            sub_agent = LumosCodeAgent(
                model_provider=self.model_provider,
                api_key=self.api_key,
                api_base=self.api_base,
                model_name=self.model_name,
                mode_manager=self.mode_manager,
                max_iterations=80,  # 调研任务需要更多轮次
                system_prompt=system_prompt,
                session_id=f"{self.session_id}_research_{topic[:20]}" if self.session_id else None,
            )

            # 执行调研
            result = await sub_agent.invoke(f"请对 {topic} 进行调研: {description}")

            if isinstance(result, dict):
                return result.get("output", str(result))
            return str(result)

        except ImportError:
            # SDK 不可用，使用简化的调研流程
            return await self._fallback_research(topic, description, output_format)

        except Exception as e:
            return f"调研执行异常: {str(e)}"

    async def _fallback_research(
        self,
        topic: str,
        description: str,
        output_format: str
    ) -> str:
        """回退调研方法

        当 SDK 不可用时，使用简化的调研流程
        """
        from .web_search_tools import WebSearchTool
        from .web_tools import WebFetchTool

        results = []

        # 1. 执行网络搜索
        search_tool = WebSearchTool()
        search_query = f"{topic} {description[:50]}"
        search_result = await search_tool.ainvoke({
            "query": search_query,
            "num_results": 5
        })
        results.append(f"## 搜索结果\n{search_result}")

        # 2. 尝试获取前几个网页的详细内容
        # 从搜索结果中提取 URL
        import re
        urls = re.findall(r'https?://[^\s\)]+', search_result)[:3]

        web_fetch_tool = WebFetchTool()
        for url in urls:
            try:
                fetch_result = await web_fetch_tool.ainvoke({
                    "url": url,
                    "prompt": f"提取关于 {topic} 的关键信息: {description}"
                })
                results.append(f"## 网页内容: {url}\n{fetch_result[:2000]}")
            except Exception:
                continue

        # 3. 整理输出
        output = f"""# 调研报告: {topic}

## 调研要求
{description}

## 调研结果

{chr(10).join(results)}

---
*注: 此为简化调研结果。完整调研需要配置 LLM API。*
"""

        return output

    def get_tool_info(self) -> ToolInfo:
        """获取工具信息"""
        return ToolInfo(
            type="function",
            name=self.name,
            description=self.description,
            parameters=Parameters(
                type="object",
                properties={
                    "topic": {
                        "type": "string",
                        "description": "调研主题"
                    },
                    "description": {
                        "type": "string",
                        "description": "详细调研要求"
                    },
                    "output_format": {
                        "type": "string",
                        "description": "输出格式: summary, detailed, table",
                        "enum": ["summary", "detailed", "table"]
                    }
                },
                required=["topic", "description"]
            )
        )


# ==================== ParallelResearchTool ====================

class ParallelResearchTool(Tool):
    """并发调研工具

    并发启动多个调研子代理，同时调研多个主题。
    适用于竞品分析、多维度调研等场景。
    """

    def __init__(
        self,
        mode_manager: Optional[AgentModeManager] = None,
        session_id: Optional[str] = None,
        model_provider: str = "openai",
        api_key: Optional[str] = None,
        api_base: Optional[str] = None,
        model_name: str = "gpt-4o",
        max_concurrent: int = 5
    ):
        super().__init__()
        self.mode_manager = mode_manager
        self.session_id = session_id
        self.model_provider = model_provider
        self.api_key = api_key
        self.api_base = api_base
        self.model_name = model_name
        self.max_concurrent = max_concurrent

        self.name = "parallel_research"
        self.description = """并发执行多个调研任务。

使用场景:
- 竞品分析: 同时调研多个竞争对手
- 多维度调研: 从不同角度调研同一主题
- 批量信息收集: 同时收集多个主题的信息

参数:
- topics: 调研主题列表（必需）
- common_requirements: 所有主题的共同调研要求（必需）
- output_format: 输出格式 (individual/comparison/table)
- max_concurrent: 最大并发数（默认 5）

示例:
- topics: ["Cursor", "GitHub Copilot", "Windsurf"]
- common_requirements: "分析核心功能、定价策略、技术特点"
- output_format: "comparison"

输出:
- individual: 每个主题单独输出
- comparison: 对比分析报告
- table: 对比表格
"""
        self.params = [
            Param(
                name="topics",
                description="调研主题列表（JSON 数组格式）",
                param_type="string",
                required=True
            ),
            Param(
                name="common_requirements",
                description="所有主题的共同调研要求",
                param_type="string",
                required=True
            ),
            Param(
                name="output_format",
                description="输出格式: individual(单独), comparison(对比), table(表格)",
                param_type="string",
                required=False
            ),
            Param(
                name="max_concurrent",
                description="最大并发数（默认 5）",
                param_type="integer",
                required=False
            ),
        ]

    def invoke(self, inputs: dict, **kwargs) -> str:
        """同步调用"""
        return asyncio.run(self.ainvoke(inputs, **kwargs))

    async def ainvoke(self, inputs: dict, **kwargs) -> str:  # noqa: ARG002
        """异步调用"""
        import json

        topics_input = inputs.get("topics", "")
        common_requirements = inputs.get("common_requirements", "").strip()
        output_format = inputs.get("output_format", "comparison")
        max_concurrent = inputs.get("max_concurrent", self.max_concurrent)

        # 解析主题列表
        if isinstance(topics_input, str):
            try:
                topics = json.loads(topics_input)
            except json.JSONDecodeError:
                # 尝试按逗号分割
                topics = [t.strip() for t in topics_input.split(",") if t.strip()]
        elif isinstance(topics_input, list):
            topics = topics_input
        else:
            return "错误: topics 参数格式无效，请使用 JSON 数组或逗号分隔的字符串"

        if not topics:
            return "错误: 未指定调研主题"
        if not common_requirements:
            return "错误: 未指定调研要求"

        # 限制并发数
        max_concurrent = min(max(1, max_concurrent), 10)

        # 并发执行调研
        try:
            results = await self._execute_parallel_research(
                topics=topics,
                common_requirements=common_requirements,
                max_concurrent=max_concurrent
            )

            # 根据输出格式整理结果
            return self._format_results(results, output_format, common_requirements)

        except Exception as e:
            return f"错误: 并发调研执行失败 - {str(e)}"

    async def _execute_parallel_research(
        self,
        topics: List[str],
        common_requirements: str,
        max_concurrent: int
    ) -> Dict[str, str]:
        """并发执行多个调研任务

        使用 asyncio.Semaphore 控制并发数
        """
        semaphore = asyncio.Semaphore(max_concurrent)
        results: Dict[str, str] = {}

        async def research_with_semaphore(topic: str) -> tuple:
            async with semaphore:
                research_tool = ResearchAgentTool(
                    mode_manager=self.mode_manager,
                    session_id=self.session_id,
                    model_provider=self.model_provider,
                    api_key=self.api_key,
                    api_base=self.api_base,
                    model_name=self.model_name
                )

                result = await research_tool.ainvoke({
                    "topic": topic,
                    "description": common_requirements,
                    "output_format": "detailed"
                })

                return topic, result

        # 创建所有任务
        tasks = [research_with_semaphore(topic) for topic in topics]

        # 并发执行
        completed = await asyncio.gather(*tasks, return_exceptions=True)

        # 收集结果
        for item in completed:
            if isinstance(item, Exception):
                continue
            topic, result = item
            results[topic] = result

        return results

    def _format_results(
        self,
        results: Dict[str, str],
        output_format: str,
        common_requirements: str
    ) -> str:
        """格式化调研结果"""
        if output_format == "individual":
            # 单独输出每个主题的结果
            output_parts = []
            for topic, result in results.items():
                output_parts.append(f"# {topic}\n\n{result}\n\n---\n")
            return "\n".join(output_parts)

        elif output_format == "table":
            # 表格形式输出
            return self._generate_comparison_table(results, common_requirements)

        else:  # comparison
            # 对比分析报告
            return self._generate_comparison_report(results, common_requirements)

    def _generate_comparison_table(
        self,
        results: Dict[str, str],
        common_requirements: str
    ) -> str:
        """生成对比表格"""
        topics = list(results.keys())

        # 表头
        header = "| 维度 | " + " | ".join(topics) + " |"
        separator = "|---" + "|---" * len(topics) + "|"

        # 从调研要求中提取维度
        dimensions = ["核心功能", "定价策略", "技术特点", "优势", "劣势"]

        # 构建表格行
        rows = [header, separator]
        for dim in dimensions:
            row = f"| {dim} |"
            for topic in topics:
                # 从结果中提取相关内容（简化处理）
                result = results.get(topic, "")
                # 提取与维度相关的内容（简化：取前100字符）
                content = result[:100].replace("\n", " ").replace("|", "/")
                row += f" {content}... |"
            rows.append(row)

        return f"""# 竞品对比表格

## 调研要求
{common_requirements}

{chr(10).join(rows)}

---
*注: 表格内容为自动提取，可能需要人工调整。*
"""

    def _generate_comparison_report(
        self,
        results: Dict[str, str],
        common_requirements: str
    ) -> str:
        """生成对比分析报告"""
        topics = list(results.keys())

        report_parts = [
            f"# 竞品对比分析报告",
            f"\n## 调研对象\n{', '.join(topics)}",
            f"\n## 调研要求\n{common_requirements}",
            "\n## 详细分析\n"
        ]

        for topic, result in results.items():
            report_parts.append(f"### {topic}\n\n{result}\n")

        report_parts.append("\n## 总结对比\n")
        report_parts.append("| 产品 | 核心优势 | 主要劣势 |")
        report_parts.append("|------|----------|----------|")
        for topic in topics:
            report_parts.append(f"| {topic} | 待分析 | 待分析 |")

        report_parts.append("\n---\n*报告生成完成。建议人工审核和补充分析。*")

        return "\n".join(report_parts)

    def get_tool_info(self) -> ToolInfo:
        """获取工具信息"""
        return ToolInfo(
            type="function",
            name=self.name,
            description=self.description,
            parameters=Parameters(
                type="object",
                properties={
                    "topics": {
                        "type": "string",
                        "description": "调研主题列表（JSON 数组格式或逗号分隔）"
                    },
                    "common_requirements": {
                        "type": "string",
                        "description": "所有主题的共同调研要求"
                    },
                    "output_format": {
                        "type": "string",
                        "description": "输出格式",
                        "enum": ["individual", "comparison", "table"]
                    },
                    "max_concurrent": {
                        "type": "integer",
                        "description": "最大并发数"
                    }
                },
                required=["topics", "common_requirements"]
            )
        )


# ==================== 工具工厂 ====================

def create_research_agent_tool(
    mode_manager: Optional[AgentModeManager] = None,
    session_id: Optional[str] = None,
    model_provider: str = "openai",
    api_key: Optional[str] = None,
    api_base: Optional[str] = None,
    model_name: str = "gpt-4o"
) -> ResearchAgentTool:
    """创建调研子代理工具"""
    return ResearchAgentTool(
        mode_manager=mode_manager,
        session_id=session_id,
        model_provider=model_provider,
        api_key=api_key,
        api_base=api_base,
        model_name=model_name
    )


def create_parallel_research_tool(
    mode_manager: Optional[AgentModeManager] = None,
    session_id: Optional[str] = None,
    model_provider: str = "openai",
    api_key: Optional[str] = None,
    api_base: Optional[str] = None,
    model_name: str = "gpt-4o",
    max_concurrent: int = 5
) -> ParallelResearchTool:
    """创建并发调研工具"""
    return ParallelResearchTool(
        mode_manager=mode_manager,
        session_id=session_id,
        model_provider=model_provider,
        api_key=api_key,
        api_base=api_base,
        model_name=model_name,
        max_concurrent=max_concurrent
    )
