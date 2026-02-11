"""
Task 子代理工具实现

提供 Task 工具，允许主 Agent 启动子代理执行独立任务
"""

import os
import asyncio
import json
import uuid
from typing import List, Optional, Dict, Any, Callable, Awaitable
from dataclasses import dataclass
from enum import Enum
from ..core.tool import Tool, ToolInfo, Parameters, Param

from ..agents.mode_manager import AgentModeManager, AgentMode
from ..llm.model_router import ModelRouter, create_model_router


# ==================== 子代理类型 ====================

class SubAgentType(Enum):
    """子代理类型"""
    EXPLORE = "Explore"      # 代码探索
    PLAN = "Plan"            # 实现规划
    BASH = "Bash"            # 命令执行
    GENERAL = "general-purpose"  # 通用代理
    RESEARCH = "Research"    # 调研代理


# ==================== 子代理配置 ====================

@dataclass
class SubAgentConfig:
    """子代理配置"""
    agent_type: SubAgentType
    description: str
    allowed_tools: List[str]
    max_turns: int = 10


# 子代理配置映射
SUBAGENT_CONFIGS: Dict[str, SubAgentConfig] = {
    "Explore": SubAgentConfig(
        agent_type=SubAgentType.EXPLORE,
        description="快速探索代码库，查找文件、搜索代码、回答代码库相关问题",
        allowed_tools=["read_file", "grep", "glob", "ls"],
        max_turns=50
    ),
    "Plan": SubAgentConfig(
        agent_type=SubAgentType.PLAN,
        description="设计实现方案，识别关键文件，考虑架构权衡",
        allowed_tools=["read_file", "grep", "glob", "ls", "todo_write"],
        max_turns=50
    ),
    "Bash": SubAgentConfig(
        agent_type=SubAgentType.BASH,
        description="执行命令行任务，如 git 操作、构建、测试等",
        allowed_tools=["bash", "read_file"],
        max_turns=50
    ),
    "general-purpose": SubAgentConfig(
        agent_type=SubAgentType.GENERAL,
        description="通用代理，可执行复杂的多步骤任务",
        allowed_tools=["read_file", "write_file", "edit_file", "bash", "grep", "glob", "ls", "todo_write"],
        max_turns=50
    ),
    "Research": SubAgentConfig(
        agent_type=SubAgentType.RESEARCH,
        description="调研代理，具备网络搜索、网页抓取、浏览器自动化能力，用于竞品分析、技术调研等",
        allowed_tools=["web_search", "web_fetch", "browser_open", "browser_snapshot", "browser_scroll", "browser_screenshot"],
        max_turns=30  # 调研任务：30 次足够获取 3-5 个有效信息源
    ),
}


# ==================== Task 工具 ====================

class TaskTool(Tool):
    """Task 子代理工具

    启动子代理执行独立任务，返回执行结果。
    子代理有独立的上下文，不会污染主对话。
    """

    # 子任务事件回调类型
    SubtaskEventCallback = Callable[[Dict[str, Any]], Awaitable[None]]

    def __init__(
        self,
        mode_manager: Optional[AgentModeManager] = None,
        session_id: Optional[str] = None,
        model_provider: str = "openai",
        api_key: Optional[str] = None,
        api_base: Optional[str] = None,
        model_name: str = "gpt-4o",
        model_router: Optional[ModelRouter] = None,
        subtask_event_callback: Optional["TaskTool.SubtaskEventCallback"] = None
    ):
        super().__init__()
        self.mode_manager = mode_manager
        self.session_id = session_id
        # LLM 配置（传递给子代理）
        self.model_provider = model_provider
        self.api_key = api_key
        self.api_base = api_base
        self.model_name = model_name
        # 模型路由器（用于子 Agent 模型选择）
        self.model_router = model_router
        # 子任务事件回调（用于向前端发送子任务进度）
        self._subtask_event_callback = subtask_event_callback

        self.name = "task"
        self.description = """启动子代理执行独立任务，支持并行执行多个任务。

子代理类型:
- Explore: 快速探索代码库，查找文件和搜索代码
- Plan: 设计实现方案，识别关键文件
- Bash: 执行命令行任务
- general-purpose: 通用代理，执行复杂多步骤任务
- Research: 调研代理，具备网络搜索、网页抓取、浏览器自动化能力

使用方式:
1. 单任务模式: 提供 description, prompt, subagent_type
2. 并行模式: 提供 tasks 数组，每个元素包含 description, prompt, subagent_type

并行执行示例:
{
  "tasks": [
    {"description": "分析 Claude Code", "prompt": "...", "subagent_type": "Research"},
    {"description": "分析 Cursor", "prompt": "...", "subagent_type": "Research"}
  ]
}

注意:
- 并行模式下所有子代理同时启动，显著提升效率
- 子代理执行完成后返回汇总结果
- 最多支持 1 层嵌套（子代理不能再启动子代理）
"""
        self.params = [
            Param(
                name="description",
                description="任务简短描述（3-5 词）",
                param_type="string",
                required=False  # 改为可选，支持批量模式
            ),
            Param(
                name="prompt",
                description="详细的任务说明",
                param_type="string",
                required=False  # 改为可选，支持批量模式
            ),
            Param(
                name="subagent_type",
                description="子代理类型: Explore, Plan, Bash, general-purpose, Research",
                param_type="string",
                required=False  # 改为可选，支持批量模式
            ),
            Param(
                name="max_turns",
                description="最大执行轮数（可选）",
                param_type="integer",
                required=False
            ),
            Param(
                name="tasks",
                description="批量任务列表，用于并行执行多个子代理。每个任务包含 description, prompt, subagent_type",
                param_type="array",
                required=False
            ),
        ]

    def invoke(self, inputs: dict, **kwargs) -> str:
        """同步调用"""
        return asyncio.run(self.ainvoke(inputs, **kwargs))

    async def ainvoke(self, inputs: dict, **kwargs) -> str:
        """异步调用"""
        # 检查是否是批量任务模式
        tasks = inputs.get("tasks")

        # 如果 tasks 是字符串，尝试解析为 JSON
        if tasks and isinstance(tasks, str):
            try:
                tasks = json.loads(tasks)
            except json.JSONDecodeError:
                return f"错误: tasks 参数格式无效，应为 JSON 数组"

        if tasks and isinstance(tasks, list) and len(tasks) > 0:
            return await self._execute_parallel_tasks(tasks)

        # 单任务模式
        description = inputs.get("description", "")
        prompt = inputs.get("prompt", "")
        subagent_type = inputs.get("subagent_type", "general-purpose")
        max_turns = inputs.get("max_turns")

        if not description:
            return """错误: 未提供任务描述 (description 参数为空)

请使用以下格式调用 task:
{
  "description": "任务简短描述",
  "prompt": "详细的任务说明",
  "subagent_type": "Research"  // 可选: Explore, Plan, Bash, general-purpose, Research
}"""

        if not prompt:
            return """错误: 未提供任务说明 (prompt 参数为空)

请使用以下格式调用 task:
{
  "description": "任务简短描述",
  "prompt": "详细的任务说明",
  "subagent_type": "Research"
}"""

        # 获取子代理配置
        config = SUBAGENT_CONFIGS.get(subagent_type)
        if not config:
            available_types = ", ".join(SUBAGENT_CONFIGS.keys())
            return f"错误: 无效的子代理类型 '{subagent_type}'。可用类型: {available_types}"

        # 使用配置的 max_turns 或用户指定的值
        actual_max_turns = max_turns if max_turns else config.max_turns

        # 检查模式限制
        if self.mode_manager:
            current_mode = self.mode_manager.get_current_mode()
            if current_mode == AgentMode.PLAN:
                # PLAN 模式下只允许 Explore 和 Plan 子代理
                if subagent_type not in ["Explore", "Plan"]:
                    return f"错误: 在 PLAN 模式下只能使用 Explore 或 Plan 子代理，不能使用 {subagent_type}。"
            elif current_mode == AgentMode.REVIEW:
                # REVIEW 模式下允许 Explore 和 Bash 子代理（Bash 用于执行只读命令如 gh pr list）
                if subagent_type not in ["Explore", "Bash"]:
                    return f"错误: 在 REVIEW 模式下只能使用 Explore 或 Bash 子代理，不能使用 {subagent_type}。"

        # 执行子代理任务
        try:
            result = await self._execute_subagent(
                description=description,
                prompt=prompt,
                config=config,
                max_turns=actual_max_turns
            )
            return result
        except Exception as e:
            return f"错误: 子代理执行失败 - {str(e)}"

    async def _emit_subtask_event(self, event_data: Dict[str, Any]):
        """发送子任务事件到回调"""
        if self._subtask_event_callback:
            try:
                await self._subtask_event_callback(event_data)
            except Exception as e:
                print(f"[Task] 子任务事件回调错误: {e}")

    async def _execute_parallel_tasks(self, tasks: List[Dict[str, Any]]) -> str:
        """并行执行多个子代理任务

        Args:
            tasks: 任务列表，每个任务包含 description, prompt, subagent_type

        Returns:
            所有任务的汇总结果
        """
        if not tasks:
            return "错误: 任务列表为空"

        total_tasks = len(tasks)
        print(f"\n[Task] ⚡ 启动并行执行，共 {total_tasks} 个子代理任务")

        # 为每个任务生成唯一 ID
        task_ids = [str(uuid.uuid4())[:8] for _ in tasks]

        # 准备所有任务的协程
        async def execute_single_task(
            task: Dict[str, Any],
            index: int,
            task_id: str
        ) -> tuple[int, str, str]:
            """执行单个任务并返回结果"""
            description = task.get("description", f"任务{index + 1}")
            prompt = task.get("prompt", "")
            subagent_type = task.get("subagent_type", "general-purpose")
            max_turns = task.get("max_turns")

            # 发送任务开始事件
            await self._emit_subtask_event({
                "task_id": task_id,
                "description": description,
                "status": "starting",
                "index": index,
                "total": total_tasks,
                "is_parallel": True
            })

            if not prompt:
                await self._emit_subtask_event({
                    "task_id": task_id,
                    "description": description,
                    "status": "error",
                    "index": index,
                    "total": total_tasks,
                    "message": "错误: 未提供任务说明",
                    "is_parallel": True
                })
                return (index, description, "错误: 未提供任务说明")

            config = SUBAGENT_CONFIGS.get(subagent_type)
            if not config:
                error_msg = f"错误: 无效的子代理类型 '{subagent_type}'"
                await self._emit_subtask_event({
                    "task_id": task_id,
                    "description": description,
                    "status": "error",
                    "index": index,
                    "total": total_tasks,
                    "message": error_msg,
                    "is_parallel": True
                })
                return (index, description, error_msg)

            actual_max_turns = max_turns if max_turns else config.max_turns

            try:
                result = await self._execute_subagent_with_events(
                    description=description,
                    prompt=prompt,
                    config=config,
                    max_turns=actual_max_turns,
                    task_id=task_id,
                    task_index=index,
                    total_tasks=total_tasks,
                    is_parallel=True
                )
                # 发送任务完成事件
                await self._emit_subtask_event({
                    "task_id": task_id,
                    "description": description,
                    "status": "completed",
                    "index": index,
                    "total": total_tasks,
                    "is_parallel": True
                })
                return (index, description, result)
            except Exception as e:
                await self._emit_subtask_event({
                    "task_id": task_id,
                    "description": description,
                    "status": "error",
                    "index": index,
                    "total": total_tasks,
                    "message": str(e),
                    "is_parallel": True
                })
                return (index, description, f"错误: {str(e)}")

        # 并行执行所有任务
        coroutines = [
            execute_single_task(task, i, task_ids[i])
            for i, task in enumerate(tasks)
        ]
        results = await asyncio.gather(*coroutines, return_exceptions=True)

        print(f"[Task] ✅ 并行执行完成，所有 {total_tasks} 个任务已结束\n")

        # 汇总结果
        output_parts = [f"## 并行任务执行结果（共 {len(tasks)} 个任务）\n"]
        for result in results:
            if isinstance(result, BaseException):
                output_parts.append(f"### 任务执行异常\n{str(result)}\n")
            elif isinstance(result, tuple) and len(result) == 3:
                index, desc, content = result
                output_parts.append(f"### 任务 {index + 1}: {desc}\n{content}\n")
            else:
                output_parts.append(f"### 未知结果\n{str(result)}\n")

        return "\n".join(output_parts)

    async def _execute_subagent_with_events(
        self,
        description: str,
        prompt: str,
        config: SubAgentConfig,
        max_turns: int,
        task_id: str,
        task_index: int,
        total_tasks: int,
        is_parallel: bool = False
    ) -> str:
        """执行子代理任务（带事件回调）"""
        return await self._execute_subagent(
            description=description,
            prompt=prompt,
            config=config,
            max_turns=max_turns,
            task_id=task_id,
            task_index=task_index,
            total_tasks=total_tasks,
            is_parallel=is_parallel
        )

    async def _execute_subagent(
        self,
        description: str,
        prompt: str,
        config: SubAgentConfig,
        max_turns: int,
        task_id: Optional[str] = None,
        task_index: int = 0,
        total_tasks: int = 1,
        is_parallel: bool = False
    ) -> str:
        """执行子代理任务

        注意：这是一个简化实现。完整实现需要：
        1. 创建独立的 Agent 实例
        2. 配置允许的工具
        3. 执行任务并收集结果
        4. 返回最终结果

        当前实现使用模拟方式，实际集成需要与 lumos SDK 的 Agent 系统对接。
        """
        # 生成 task_id 如果没有提供
        if not task_id:
            task_id = str(uuid.uuid4())[:8]
        # 构建子代理系统提示词
        system_prompt = f"""你是一个 {config.agent_type.value} 子代理，负责执行特定任务并返回结果。

## 任务描述
{description}

## 你的职责
{config.description}

## 可用工具
{', '.join(config.allowed_tools)}

## 重要规则（必须严格遵守！）

1. **效率优先**：用最少的工具调用完成任务，不要过度收集信息
2. **及时总结**：收集到足够回答问题的信息后，立即停止并返回结果
3. **明确完成**：当你认为已经获得足够信息时，直接输出总结，不要继续调用工具
4. **避免重复**：不要重复访问相同或相似的 URL
5. **处理失败**：遇到 404/403/连接失败时，跳过该资源，不要反复尝试

## 完成标准
- 对于调研任务：获取 3-5 个有效信息源后即可总结
- 对于探索任务：找到目标文件/代码后立即返回
- 对于执行任务：完成指定操作后立即返回结果

## 输出格式
完成任务后，直接输出结构化的总结结果，不要说"让我继续..."或"我还需要..."

## 任务内容
{prompt}
"""

        # 尝试使用 lumos SDK 创建子代理
        try:
            from ..agents.lumos_agent import LumosCodeAgent

            # 根据子代理类型选择模型配置
            if self.model_router:
                model_config = self.model_router.get_model_for_agent(config.agent_type.value)
                sub_model_provider = model_config.get("provider", self.model_provider)
                sub_model_name = model_config.get("model", self.model_name)
                sub_api_base = model_config.get("api_base_url", self.api_base)
                sub_api_key = model_config.get("api_key", self.api_key)
            else:
                sub_model_provider = self.model_provider
                sub_model_name = self.model_name
                sub_api_base = self.api_base
                sub_api_key = self.api_key

            # 调试日志
            print(f"[SubAgent] 创建子代理: type={config.agent_type.value}")
            print(f"[SubAgent] provider={sub_model_provider}, model={sub_model_name}")
            print(f"[SubAgent] api_base={sub_api_base}")
            print(f"[SubAgent] api_key={'已设置' if sub_api_key else '未设置(None)'}")

            # 创建子代理（使用受限的工具集）
            sub_agent = LumosCodeAgent(
                model_provider=sub_model_provider,
                api_key=sub_api_key,
                api_base=sub_api_base,
                model_name=sub_model_name,
                mode_manager=self.mode_manager,
                max_iterations=max_turns,
                system_prompt=system_prompt,
                session_id=f"{self.session_id}_sub_{config.agent_type.value}" if self.session_id else None
            )

            # 使用流式调用，显示子 Agent 执行进度
            task_label = f"[SubAgent:{description[:20]}]"  # 用任务描述前20字符作为标识
            print(f"{task_label} 开始执行任务")
            final_content = ""
            content_chunks = []  # 收集流式内容块
            tool_calls_count = 0

            async for event in sub_agent.stream(prompt):
                if event.type == "content_chunk":
                    # 收集流式内容块
                    if event.data:
                        content_chunks.append(str(event.data))
                elif event.type == "content":
                    final_content = event.data
                elif event.type == "tool_call":
                    tool_calls_count += 1
                    tool_info = event.data
                    tool_name = (
                        tool_info.get("name", "unknown")
                        if isinstance(tool_info, dict)
                        else str(tool_info)
                    )
                    print(f"{task_label} 调用工具 #{tool_calls_count}: {tool_name}")
                    # 发送工具调用事件
                    await self._emit_subtask_event({
                        "task_id": task_id,
                        "description": description,
                        "status": "tool_call",
                        "index": task_index,
                        "total": total_tasks,
                        "tool_name": tool_name,
                        "tool_count": tool_calls_count,
                        "is_parallel": is_parallel
                    })
                elif event.type == "tool_result":
                    result_str = str(event.data)
                    result_preview = (
                        result_str[:100] + "..."
                        if len(result_str) > 100
                        else result_str
                    )
                    print(f"{task_label} 工具结果: {result_preview}")
                    # 发送工具结果事件
                    await self._emit_subtask_event({
                        "task_id": task_id,
                        "description": description,
                        "status": "tool_result",
                        "index": task_index,
                        "total": total_tasks,
                        "tool_count": tool_calls_count,
                        "message": result_preview,
                        "is_parallel": is_parallel
                    })
                elif event.type == "error":
                    print(f"{task_label} 错误: {event.data}")
                    await self._emit_subtask_event({
                        "task_id": task_id,
                        "description": description,
                        "status": "error",
                        "index": task_index,
                        "total": total_tasks,
                        "message": str(event.data),
                        "is_parallel": is_parallel
                    })
                    return f"子代理执行错误: {event.data}"

            print(f"{task_label} 任务完成，共调用 {tool_calls_count} 次工具")

            # 优先使用完整内容，否则拼接流式内容块
            if final_content:
                return final_content
            elif content_chunks:
                return "".join(content_chunks)
            else:
                return "子代理执行完成，但未返回内容"

        except ImportError:
            # SDK 不可用，返回模拟结果
            return f"""## 子代理执行结果

**类型**: {config.agent_type.value}
**任务**: {description}

**说明**: 子代理功能需要完整的 lumos SDK 支持。
当前为模拟模式，实际执行需要配置 LLM API。

**任务提示**:
{prompt[:500]}{'...' if len(prompt) > 500 else ''}

**建议**: 请手动执行上述任务，或配置 LLM API 后重试。
"""

        except Exception as e:
            return f"子代理执行异常: {str(e)}"

    def get_tool_info(self) -> ToolInfo:
        """获取工具信息"""
        return ToolInfo(
            type="function",
            name=self.name,
            description=self.description,
            parameters=Parameters(
                type="object",
                properties={
                    "description": {
                        "type": "string",
                        "description": "任务简短描述（3-5 词）"
                    },
                    "prompt": {
                        "type": "string",
                        "description": "详细的任务说明"
                    },
                    "subagent_type": {
                        "type": "string",
                        "description": "子代理类型",
                        "enum": list(SUBAGENT_CONFIGS.keys())
                    },
                    "max_turns": {
                        "type": "integer",
                        "description": "最大执行轮数"
                    }
                },
                required=["description", "prompt", "subagent_type"]
            )
        )


# ==================== 工具工厂 ====================

def create_task_tool(
    mode_manager: Optional[AgentModeManager] = None,
    session_id: Optional[str] = None,
    model_provider: str = "openai",
    api_key: Optional[str] = None,
    api_base: Optional[str] = None,
    model_name: str = "gpt-4o",
    model_router: Optional[ModelRouter] = None,
    subtask_event_callback: Optional[TaskTool.SubtaskEventCallback] = None
) -> Tool:
    """创建 Task 工具

    Args:
        mode_manager: 模式管理器
        session_id: 会话 ID
        model_provider: 模型提供商
        api_key: API 密钥
        api_base: API Base URL
        model_name: 模型名称
        model_router: 模型路由器（用于子 Agent 模型选择）
        subtask_event_callback: 子任务事件回调

    Returns:
        Task 工具实例
    """
    return TaskTool(
        mode_manager=mode_manager,
        session_id=session_id,
        model_provider=model_provider,
        api_key=api_key,
        api_base=api_base,
        model_name=model_name,
        model_router=model_router,
        subtask_event_callback=subtask_event_callback
    )
