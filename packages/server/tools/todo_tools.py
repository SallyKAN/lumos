"""
TodoWrite 工具实现

用于任务管理的 TodoWrite 工具，支持任务的创建、更新和列表显示。
参考：docs/02-详细技术设计.md 第 8.6 节
"""

import os
import json
import uuid
from datetime import datetime
from typing import List, Optional, Dict, Any
from pathlib import Path
from dataclasses import dataclass

from ..core.tool import Tool, ToolInfo, Parameters, Param

# ============================================================================
# Todo 数据模型
# ============================================================================

@dataclass
class TodoItem:
    """待办事项数据模型"""
    id: str
    content: str
    activeForm: str  # 进行时形式（如"正在编写代码"）
    status: str  # "pending" | "in_progress" | "completed"
    createdAt: str
    updatedAt: str
    result: Optional[str] = None      # 任务执行结果/摘要
    completedAt: Optional[str] = None  # 完成时间

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        data = {
            "id": self.id,
            "content": self.content,
            "activeForm": self.activeForm,
            "status": self.status,
            "createdAt": self.createdAt,
            "updatedAt": self.updatedAt
        }
        if self.result is not None:
            data["result"] = self.result
        if self.completedAt is not None:
            data["completedAt"] = self.completedAt
        return data

    @staticmethod
    def from_dict(data: Dict[str, Any]) -> 'TodoItem':
        """从字典创建实例"""
        return TodoItem(
            id=data["id"],
            content=data["content"],
            activeForm=data["activeForm"],
            status=data["status"],
            createdAt=data["createdAt"],
            updatedAt=data["updatedAt"],
            result=data.get("result"),
            completedAt=data.get("completedAt")
        )


# ============================================================================
# Todo 持久化管理器
# ============================================================================

class TodoPersistenceManager:
    """Todo 持久化管理器

    负责将 todos 保存到 ~/.lumos/sessions/{session_id}/todos.json
    同时支持旧路径 ~/.lumos/todos/ 的向后兼容
    """

    def __init__(self, session_id: Optional[str] = None):
        """初始化持久化管理器

        Args:
            session_id: 会话 ID（可选，默认使用时间戳）
        """
        self.session_id = session_id or datetime.now().strftime("%Y%m%d_%H%M%S")

        # 新的会话存储路径
        self.sessions_dir = Path.home() / ".lumos" / "sessions"
        self.session_dir = self.sessions_dir / self.session_id
        self.session_dir.mkdir(parents=True, exist_ok=True)
        self.file_path = self.session_dir / "todos.json"

        # 旧的存储路径（用于向后兼容）
        self.old_todos_dir = Path.home() / ".lumos" / "todos"
        self.old_file_path = self.old_todos_dir / f"{self.session_id}.json"

        # 如果旧路径存在但新路径不存在，自动迁移
        self._migrate_if_needed()

    def _migrate_if_needed(self):
        """如果需要，从旧路径迁移到新路径"""
        if self.old_file_path.exists() and not self.file_path.exists():
            try:
                import shutil
                shutil.copy2(self.old_file_path, self.file_path)
            except Exception:
                pass  # 迁移失败不影响正常使用

    def load_todos(self) -> List[TodoItem]:
        """从文件加载 todos

        Returns:
            Todo 列表
        """
        # 优先从新路径加载
        if self.file_path.exists():
            try:
                with open(self.file_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    return [TodoItem.from_dict(item) for item in data]
            except Exception as e:
                print(f"警告: 加载 todos 失败 - {str(e)}")
                return []

        # 回退到旧路径
        if self.old_file_path.exists():
            try:
                with open(self.old_file_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    return [TodoItem.from_dict(item) for item in data]
            except Exception as e:
                print(f"警告: 加载 todos 失败 - {str(e)}")
                return []

        return []

    def save_todos(self, todos: List[TodoItem]) -> bool:
        """保存 todos 到文件

        Args:
            todos: Todo 列表

        Returns:
            是否成功
        """
        try:
            data = [todo.to_dict() for todo in todos]
            with open(self.file_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            return True
        except Exception as e:
            print(f"错误: 保存 todos 失败 - {str(e)}")
            return False

    def clear_todos(self) -> bool:
        """清除所有 todos

        Returns:
            是否成功
        """
        try:
            if self.file_path.exists():
                self.file_path.unlink()
            # 同时清除旧路径的文件
            if self.old_file_path.exists():
                self.old_file_path.unlink()
            return True
        except Exception as e:
            print(f"错误: 清除 todos 失败 - {str(e)}")
            return False


# ============================================================================
# TodoWrite 工具
# ============================================================================

class TodoWriteTool(Tool):
    """TodoWrite 工具

    高层工具 - 任务管理

    用于管理 Agent 的任务列表，帮助跟踪和执行复杂任务。
    所有模式下都可用。
    """

    def __init__(self, mode_manager=None, session_id: Optional[str] = None):
        """初始化 TodoWrite 工具

        Args:
            mode_manager: 模式管理器（可选，TodoWrite 不需要权限检查）
            session_id: 会话 ID（可选）
        """
        super().__init__()
        self.mode_manager = mode_manager
        self.persistence = TodoPersistenceManager(session_id)
        self.name = "todo_write"
        self.description = """创建和管理任务列表。用于跟踪复杂任务的进度。

操作类型 (action):
- create: 创建新任务列表
- update: 更新任务状态
- list: 列出所有任务
- clear: 清除所有任务

【简化格式 - 推荐】创建任务时，可以用 tasks 参数传递简单的任务描述字符串，用换行或分号分隔多个任务：
  action: "create"
  tasks: "创建登录表单;实现表单验证;添加错误处理"

【完整格式】也可以用 todos 参数传递 JSON 数组：
  action: "create"
  todos: [{"content": "任务1", "activeForm": "正在执行任务1", "status": "in_progress"}]

更新任务（建议完成时提供 result 记录执行结果）：
  action: "update"
  task_id: "任务ID前8位"
  status: "completed"
  result: "成功创建了登录表单，包含用户名和密码输入框"

规则:
- 同一时间只能有一个任务处于 in_progress 状态
- 第一个任务自动设为 in_progress，其余为 pending
- 完成任务时建议提供 result 参数，记录执行结果便于后续恢复上下文
"""
        self.params = [
            Param(
                name="action",
                description="操作类型: create, update, list, clear",
                param_type="string",
                required=True
            ),
            Param(
                name="tasks",
                description="任务列表字符串，用分号或换行分隔多个任务（简化格式，推荐使用）",
                param_type="string",
                required=False
            ),
            Param(
                name="todos",
                description="任务列表 JSON 数组（完整格式）",
                param_type="array",
                required=False
            ),
            Param(
                name="task_id",
                description="要更新的任务 ID（前8位即可）",
                param_type="string",
                required=False
            ),
            Param(
                name="status",
                description="新状态: pending, in_progress, completed",
                param_type="string",
                required=False
            ),
            Param(
                name="result",
                description="任务执行结果摘要（完成任务时建议提供，便于后续恢复上下文）",
                param_type="string",
                required=False
            ),
        ]

    def invoke(self, inputs: dict, **kwargs) -> str:
        """同步调用"""
        import asyncio
        return asyncio.run(self.ainvoke(inputs, **kwargs))

    async def ainvoke(self, inputs: dict, **kwargs) -> str:
        """异步调用"""
        action = inputs.get("action", "")

        if not action:
            # 提供详细的错误信息和正确示例，帮助 LLM 修正
            return """错误: 未指定 action 参数

请使用以下格式调用 todo_write:
{
  "action": "create",
  "tasks": "任务1;任务2;任务3"
}

或者更新任务:
{
  "action": "update",
  "task_id": "任务ID前8位",
  "status": "completed"
}

可用的 action: create, update, list, clear"""

        # 加载现有 todos
        current_todos = self.persistence.load_todos()

        try:
            if action == "create":
                if current_todos:
                    return (
                        "错误: 已存在任务列表，不能创建新的 todo_list。"
                        "请使用 todo_modify 追加/插入任务，或使用 todo_write 更新状态。"
                    )
                # 优先使用简化格式 tasks 参数
                tasks_str = inputs.get("tasks")
                if tasks_str and isinstance(tasks_str, str):
                    return await self._create_from_string(tasks_str)

                # 其次使用完整格式 todos 参数
                todos_data = inputs.get("todos")
                if todos_data is None:
                    todos_data = inputs.get("todo_list") or inputs.get("items")

                if isinstance(todos_data, str):
                    try:
                        todos_data = json.loads(todos_data)
                    except json.JSONDecodeError:
                        # 如果是普通字符串，当作 tasks 处理
                        return await self._create_from_string(todos_data)

                if todos_data:
                    return await self._create_todos(todos_data)

                return """错误: 创建任务时需要提供 tasks 或 todos 参数

推荐使用简化格式:
  action: "create"
  tasks: "任务1;任务2;任务3"

或完整格式:
  action: "create"
  todos: [{"content": "任务1", "activeForm": "正在执行任务1", "status": "in_progress"}]"""

            elif action == "update":
                # 支持简化的更新格式
                task_id = inputs.get("task_id") or inputs.get("id")
                status = inputs.get("status")
                result = inputs.get("result")  # 任务结果（可选）

                if task_id and status:
                    return await self._update_single_task(
                        task_id, status, current_todos, result
                    )

                # 完整格式
                todos_data = inputs.get("todos")
                if todos_data:
                    if isinstance(todos_data, str):
                        try:
                            todos_data = json.loads(todos_data)
                        except json.JSONDecodeError:
                            return "错误: todos 参数格式无效"
                    return await self._update_todos(todos_data, current_todos)

                return """错误: 更新任务需要提供参数

简化格式:
  action: "update"
  task_id: "任务ID前8位"
  status: "completed"

完整格式:
  action: "update"
  todos: [{"id": "完整任务ID", "status": "completed"}]"""

            elif action == "list":
                return await self._list_todos(current_todos)
            elif action == "clear":
                return await self._clear_todos()
            else:
                return f"错误: 未知的 action '{action}'。支持: create, update, list, clear"

        except Exception as e:
            return f"错误: {str(e)}"

    async def _create_from_string(self, tasks_str: str) -> str:
        """从字符串创建任务列表（简化格式）

        Args:
            tasks_str: 任务字符串，用分号或换行分隔

        Returns:
            操作结果
        """
        # 分割任务
        tasks = []
        for sep in ['\n', ';', '；', '、']:
            if sep in tasks_str:
                tasks = [t.strip() for t in tasks_str.split(sep) if t.strip()]
                break

        if not tasks:
            tasks = [tasks_str.strip()] if tasks_str.strip() else []

        if not tasks:
            return "错误: 未提供有效的任务内容"

        # 创建 TodoItem 对象
        now = datetime.now().isoformat()
        new_todos = []

        for i, task_content in enumerate(tasks):
            # 清理任务内容（移除序号前缀）
            content = task_content.strip()
            if content and content[0].isdigit() and '.' in content[:3]:
                content = content.split('.', 1)[-1].strip()

            if not content:
                continue

            # 自动生成 activeForm
            active_form = f"正在{content}" if not content.startswith("正在") else content

            # 第一个任务为 in_progress，其余为 pending
            status = "in_progress" if i == 0 else "pending"

            todo_item = TodoItem(
                id=str(uuid.uuid4()),
                content=content,
                activeForm=active_form,
                status=status,
                createdAt=now,
                updatedAt=now
            )
            new_todos.append(todo_item)

        if not new_todos:
            return "错误: 未能解析出有效的任务"

        # 保存到文件
        if not self.persistence.save_todos(new_todos):
            return "错误: 保存任务列表失败"

        # 返回创建结果
        result = f"成功创建 {len(new_todos)} 个任务:\n"
        for i, todo in enumerate(new_todos):
            status_icon = "🔄" if todo.status == "in_progress" else "⏳"
            result += f"  {status_icon} [{todo.id[:8]}] {todo.content}\n"

        # 添加继续执行的提示 - 明确告诉 LLM 下一步应该做什么
        first_task = new_todos[0].content if new_todos else ""
        result += f"\n\n🚀 下一步：立即执行任务「{first_task}」- 调用相应的工具（如 write_file、edit_file 等）"

        return result.strip()

    async def _update_single_task(
        self,
        task_id: str,
        status: str,
        current_todos: List[TodoItem],
        result: Optional[str] = None
    ) -> str:
        """更新单个任务状态（简化格式）

        Args:
            task_id: 任务 ID（可以是前8位）
            status: 新状态
            current_todos: 当前任务列表
            result: 任务执行结果（可选，completed 时建议提供）

        Returns:
            操作结果
        """
        if not current_todos:
            return "错误: 当前没有任务可以更新"

        if status not in ["pending", "in_progress", "completed"]:
            return f"错误: 无效的 status '{status}'，必须是 pending/in_progress/completed"

        # 查找任务（支持前缀匹配）
        found_todo = None
        for todo in current_todos:
            if todo.id.startswith(task_id) or todo.id == task_id:
                found_todo = todo
                break

        if not found_todo:
            return f"错误: 未找到 ID 以 '{task_id}' 开头的任务"

        # 如果设为 in_progress，先将其他 in_progress 任务改为 pending
        if status == "in_progress":
            for todo in current_todos:
                if todo.status == "in_progress" and todo.id != found_todo.id:
                    todo.status = "pending"
                    todo.updatedAt = datetime.now().isoformat()

        # 更新状态
        now = datetime.now().isoformat()
        old_status = found_todo.status
        found_todo.status = status
        found_todo.updatedAt = now

        # 如果完成，记录结果和完成时间
        if status == "completed":
            found_todo.completedAt = now
            if result:
                found_todo.result = result

        # 保存
        if not self.persistence.save_todos(current_todos):
            return "错误: 保存任务列表失败"

        status_icons = {"pending": "⏳", "in_progress": "🔄", "completed": "✅"}
        msg = f"任务 [{found_todo.id[:8]}] 状态更新: {status_icons.get(old_status, '?')} → {status_icons.get(status, '?')}"
        if result and status == "completed":
            msg += f"\n结果已记录: {result[:50]}{'...' if len(result) > 50 else ''}"
        return msg

    async def _create_todos(self, todos_data: List[Dict]) -> str:
        """创建新的任务列表

        Args:
            todos_data: 任务数据列表

        Returns:
            操作结果
        """
        if not todos_data:
            return """错误: 创建任务时必须提供 todos 参数

正确格式示例:
{
  "action": "create",
  "todos": [
    {"content": "第一个任务", "activeForm": "正在执行第一个任务", "status": "in_progress"},
    {"content": "第二个任务", "activeForm": "正在执行第二个任务", "status": "pending"}
  ]
}

请重新调用 todo_write，确保 todos 参数是一个包含任务对象的数组。"""

        # 验证只有一个 in_progress 任务
        in_progress_count = sum(
            1 for todo in todos_data
            if todo.get("status") == "in_progress"
        )
        if in_progress_count > 1:
            return "错误: 同一时间只能有一个任务处于 in_progress 状态"

        # 创建 TodoItem 对象
        now = datetime.now().isoformat()
        new_todos = []
        for todo_data in todos_data:
            # 验证必需字段
            if "content" not in todo_data:
                return f"错误: 任务缺少 content 字段"
            if "activeForm" not in todo_data:
                return f"错误: 任务 '{todo_data.get('content', '')}' 缺少 activeForm 字段"
            if "status" not in todo_data:
                return f"错误: 任务 '{todo_data.get('content', '')}' 缺少 status 字段"

            # 验证状态值
            status = todo_data["status"]
            if status not in ["pending", "in_progress", "completed"]:
                return f"错误: 无效的 status '{status}'，必须是 pending/in_progress/completed 之一"

            todo_item = TodoItem(
                id=str(uuid.uuid4()),
                content=todo_data["content"],
                activeForm=todo_data["activeForm"],
                status=status,
                createdAt=now,
                updatedAt=now
            )
            new_todos.append(todo_item)

        # 保存到文件
        if not self.persistence.save_todos(new_todos):
            return "错误: 保存任务列表失败"

        return f"成功创建 {len(new_todos)} 个任务"

    async def _update_todos(
        self,
        todos_data: List[Dict],
        current_todos: List[TodoItem]
    ) -> str:
        """更新现有任务

        Args:
            todos_data: 更新的任务数据
            current_todos: 当前任务列表

        Returns:
            操作结果
        """
        if not current_todos:
            return "错误: 当前没有任务可以更新。请先使用 action=create 创建任务"

        if not todos_data:
            return "错误: 更新任务时必须提供 todos 参数"

        # 验证只有一个 in_progress 任务
        in_progress_count = sum(
            1 for todo in todos_data
            if todo.get("status") == "in_progress"
        )
        if in_progress_count > 1:
            return "错误: 同一时间只能有一个任务处于 in_progress 状态"

        # 更新任务
        updated_todos = []
        now = datetime.now().isoformat()

        for todo_data in todos_data:
            todo_id = todo_data.get("id")

            if not todo_id:
                return "错误: 更新任务时必须提供 id"

            # 查找对应的任务
            found = False
            for current_todo in current_todos:
                if current_todo.id == todo_id:
                    # 更新字段
                    if "content" in todo_data:
                        current_todo.content = todo_data["content"]
                    if "activeForm" in todo_data:
                        current_todo.activeForm = todo_data["activeForm"]
                    if "status" in todo_data:
                        status = todo_data["status"]
                        if status not in ["pending", "in_progress", "completed"]:
                            return f"错误: 无效的 status '{status}'"
                        current_todo.status = status
                    current_todo.updatedAt = now
                    found = True
                    break

            if not found:
                return f"错误: 未找到 id 为 '{todo_id}' 的任务"

            updated_todos.append(current_todo)

        # 保存到文件
        if not self.persistence.save_todos(current_todos):
            return "错误: 保存任务列表失败"

        return f"成功更新 {len(updated_todos)} 个任务"

    async def _list_todos(self, todos: List[TodoItem]) -> str:
        """列出所有任务

        Args:
            todos: 任务列表

        Returns:
            格式化的任务列表
        """
        if not todos:
            return "当前没有任务"

        # 按状态分组
        pending = [t for t in todos if t.status == "pending"]
        in_progress = [t for t in todos if t.status == "in_progress"]
        completed = [t for t in todos if t.status == "completed"]

        result_lines = [f"任务列表 (共 {len(todos)} 个):\n"]

        # in_progress
        if in_progress:
            result_lines.append("🔄 进行中:")
            for todo in in_progress:
                result_lines.append(f"  [{todo.id[:8]}] {todo.activeForm}")
            result_lines.append("")

        # pending
        if pending:
            result_lines.append("⏳ 待处理:")
            for todo in pending:
                result_lines.append(f"  [{todo.id[:8]}] {todo.content}")
            result_lines.append("")

        # completed（显示结果摘要）
        if completed:
            result_lines.append("✅ 已完成:")
            for todo in completed:
                line = f"  [{todo.id[:8]}] {todo.content}"
                if todo.result:
                    # 显示结果摘要（最多 60 字符）
                    result_summary = todo.result[:60]
                    if len(todo.result) > 60:
                        result_summary += "..."
                    line += f"\n      → 结果: {result_summary}"
                result_lines.append(line)

        return "\n".join(result_lines)

    async def _clear_todos(self) -> str:
        """清除所有任务

        Returns:
            操作结果
        """
        if not self.persistence.clear_todos():
            return "错误: 清除任务失败"

        return "成功清除所有任务"

    def get_tool_info(self) -> ToolInfo:
        """获取工具信息"""
        return ToolInfo(
            type="function",
            name=self.name,
            description=self.description,
            parameters=Parameters(
                type="object",
                properties={
                    "action": {
                        "type": "string",
                        "description": "操作类型: create, update, list, clear",
                        "enum": ["create", "update", "list", "clear"]
                    },
                    "tasks": {
                        "type": "string",
                        "description": "任务列表字符串，用分号分隔多个任务（简化格式，推荐）。例如: '创建登录表单;实现表单验证;添加错误处理'"
                    },
                    "task_id": {
                        "type": "string",
                        "description": "要更新的任务 ID（前8位即可）"
                    },
                    "status": {
                        "type": "string",
                        "description": "新状态",
                        "enum": ["pending", "in_progress", "completed"]
                    },
                    "result": {
                        "type": "string",
                        "description": "任务执行结果摘要（完成任务时建议提供）"
                    },
                    "todos": {
                        "type": "array",
                        "description": "任务列表 JSON 数组（完整格式，可选）",
                        "items": {
                            "type": "object",
                            "properties": {
                                "id": {"type": "string"},
                                "content": {"type": "string"},
                                "activeForm": {"type": "string"},
                                "status": {"type": "string", "enum": ["pending", "in_progress", "completed"]},
                                "result": {"type": "string"}
                            }
                        }
                    }
                },
                required=["action"]
            )
        )


# ============================================================================
# TodoModify 工具
# ============================================================================

class TodoModifyTool(Tool):
    """TodoModify 工具

    用于修改现有任务列表：追加、插入、移除任务。
    当用户在任务执行中要求"再加"、"追加"、"还要"时使用。
    """

    def __init__(self, mode_manager=None, session_id: Optional[str] = None):
        super().__init__()
        self.mode_manager = mode_manager
        self.persistence = TodoPersistenceManager(session_id)
        self.name = "todo_modify"
        self.description = """修改现有任务列表。当用户要求追加、插入或移除任务时使用。

操作类型 (action):
- append: 在末尾追加新任务
- insert_after: 在指定任务后插入新任务
- remove: 移除指定任务

追加任务示例：
  用户说"再加个M9的调研"
  → todo_modify(action="append", task="调研问界M9产品特点")

在指定任务后插入示例：
  场景1：用户说"在任务A后面插入任务B"
  → todo_modify(action="insert_after", after_task_id="任务A的ID前8位", task="任务B描述")

  场景2：用户说"再把一月的也一起处理"（已有任务"查找十二月发票PDF文件"）
  → 先找到"查找十二月发票PDF文件"任务的ID，然后：
  → todo_modify(action="insert_after", after_task_id="十二月任务ID前8位", task="查找一月发票PDF文件")

移除任务：
  → todo_modify(action="remove", task_id="任务ID前8位")

重要规则:
- 当用户要求处理"类似的"或"也"、"还"相关的任务时，应该使用 insert_after 在相关任务后插入，而不是 append
- 追加的新任务状态默认为 pending
- 移除已完成的任务不影响其他任务
- 操作完成后会显示更新后的任务列表
"""
        self.params = [
            Param(
                name="action",
                description="操作类型: append, insert_after, remove",
                param_type="string",
                required=True
            ),
            Param(
                name="task",
                description=(
                    "新任务描述（append/insert_after 时使用）。"
                    "支持分号或换行分隔多个任务"
                ),
                param_type="string",
                required=False
            ),
            Param(
                name="after_task_id",
                description="在此任务后插入（insert_after 时使用，任务ID前8位）",
                param_type="string",
                required=False
            ),
            Param(
                name="task_id",
                description="目标任务ID（remove 时使用，任务ID前8位）",
                param_type="string",
                required=False
            ),
        ]

    def invoke(self, inputs: dict, **kwargs) -> str:
        """同步调用"""
        import asyncio
        return asyncio.run(self.ainvoke(inputs, **kwargs))

    async def ainvoke(self, inputs: dict, **kwargs) -> str:
        """异步调用"""
        action = inputs.get("action", "")

        if not action:
            return "错误: 未指定 action 参数。可用: append, insert_after, remove"

        current_todos = self.persistence.load_todos()

        if action == "append":
            return await self._append_task(inputs, current_todos)
        elif action == "insert_after":
            return await self._insert_after_task(inputs, current_todos)
        elif action == "remove":
            return await self._remove_task(inputs, current_todos)
        else:
            return f"错误: 未知的 action '{action}'。支持: append, insert_after, remove"

    async def _append_task(
        self, inputs: dict, current_todos: List[TodoItem]
    ) -> str:
        """在末尾追加新任务"""
        task_str = inputs.get("task", "").strip()
        tasks = self._parse_tasks_from_string(task_str)
        if not tasks:
            return "错误: append 操作需要提供 task 参数"

        now = datetime.now().isoformat()
        new_todos = []

        for task in tasks:
            active_form = f"正在{task}" if not task.startswith("正在") else task
            new_todo = TodoItem(
                id=str(uuid.uuid4()),
                content=task,
                activeForm=active_form,
                status="pending",
                createdAt=now,
                updatedAt=now
            )
            current_todos.append(new_todo)
            new_todos.append(new_todo)

        if not self.persistence.save_todos(current_todos):
            return "错误: 保存任务列表失败"

        if len(new_todos) == 1:
            new_todo = new_todos[0]
            return (
                f"✅ 已追加任务: [{new_todo.id[:8]}] {new_todo.content}\n\n"
                f"当前任务列表共 {len(current_todos)} 项，继续执行未完成的任务。"
            )

        result_lines = [f"✅ 已追加 {len(new_todos)} 个任务:"]
        for todo in new_todos:
            result_lines.append(f"  [{todo.id[:8]}] {todo.content}")
        result_lines.append("")
        result_lines.append(
            f"当前任务列表共 {len(current_todos)} 项，继续执行未完成的任务。"
        )
        return "\n".join(result_lines)

    async def _insert_after_task(
        self, inputs: dict, current_todos: List[TodoItem]
    ) -> str:
        """在指定任务后插入新任务"""
        task_str = inputs.get("task", "").strip()
        tasks = self._parse_tasks_from_string(task_str)
        after_task_id = inputs.get("after_task_id", "").strip()

        if not tasks:
            return "错误: insert_after 操作需要提供 task 参数"
        if not after_task_id:
            return "错误: insert_after 操作需要提供 after_task_id 参数"
        if not current_todos:
            return "错误: 当前没有任务列表，请先使用 todo_write 创建任务"

        # 查找目标任务
        insert_index = -1
        for i, todo in enumerate(current_todos):
            if todo.id.startswith(after_task_id) or todo.id == after_task_id:
                insert_index = i + 1
                break

        if insert_index == -1:
            return f"错误: 未找到 ID 以 '{after_task_id}' 开头的任务"

        now = datetime.now().isoformat()
        new_todos = []
        for task in tasks:
            active_form = f"正在{task}" if not task.startswith("正在") else task
            new_todo = TodoItem(
                id=str(uuid.uuid4()),
                content=task,
                activeForm=active_form,
                status="pending",
                createdAt=now,
                updatedAt=now
            )
            current_todos.insert(insert_index, new_todo)
            insert_index += 1
            new_todos.append(new_todo)

        if not self.persistence.save_todos(current_todos):
            return "错误: 保存任务列表失败"

        if len(new_todos) == 1:
            new_todo = new_todos[0]
            return (
                f"✅ 已在任务 [{after_task_id}] 后插入: "
                f"[{new_todo.id[:8]}] {new_todo.content}\n\n"
                f"当前任务列表共 {len(current_todos)} 项，继续执行未完成的任务。"
            )

        result_lines = [
            f"✅ 已在任务 [{after_task_id}] 后插入 {len(new_todos)} 个任务:"
        ]
        for todo in new_todos:
            result_lines.append(f"  [{todo.id[:8]}] {todo.content}")
        result_lines.append("")
        result_lines.append(
            f"当前任务列表共 {len(current_todos)} 项，继续执行未完成的任务。"
        )
        return "\n".join(result_lines)

    def _parse_tasks_from_string(self, tasks_str: str) -> List[str]:
        """解析任务字符串，支持分号和换行等分隔符

        Args:
            tasks_str: 任务字符串

        Returns:
            任务列表
        """
        if not tasks_str:
            return []
        tasks = []
        for sep in ['\n', ';', '；', '、']:
            if sep in tasks_str:
                tasks = [t.strip() for t in tasks_str.split(sep) if t.strip()]
                break
        if not tasks:
            tasks = [tasks_str.strip()] if tasks_str.strip() else []
        return tasks

    async def _remove_task(
        self, inputs: dict, current_todos: List[TodoItem]
    ) -> str:
        """移除指定任务"""
        task_id = inputs.get("task_id", "").strip()

        if not task_id:
            return "错误: remove 操作需要提供 task_id 参数"
        if not current_todos:
            return "错误: 当前没有任务列表"

        # 查找并移除任务
        removed_todo = None
        for i, todo in enumerate(current_todos):
            if todo.id.startswith(task_id) or todo.id == task_id:
                removed_todo = current_todos.pop(i)
                break

        if not removed_todo:
            return f"错误: 未找到 ID 以 '{task_id}' 开头的任务"

        if not self.persistence.save_todos(current_todos):
            return "错误: 保存任务列表失败"

        return (
            f"✅ 已移除任务: [{removed_todo.id[:8]}] {removed_todo.content}\n\n"
            f"当前任务列表剩余 {len(current_todos)} 项。"
        )

    def get_tool_info(self) -> ToolInfo:
        """获取工具信息"""
        return ToolInfo(
            type="function",
            name=self.name,
            description=self.description,
            parameters=Parameters(
                type="object",
                properties={
                    "action": {
                        "type": "string",
                        "description": "操作类型: append, insert_after, remove",
                        "enum": ["append", "insert_after", "remove"]
                    },
                    "task": {
                        "type": "string",
                        "description": (
                            "新任务描述（append/insert_after 时使用）。"
                            "支持分号或换行分隔多个任务"
                        )
                    },
                    "after_task_id": {
                        "type": "string",
                        "description": "在此任务后插入（insert_after 时使用）"
                    },
                    "task_id": {
                        "type": "string",
                        "description": "目标任务ID（remove 时使用）"
                    }
                },
                required=["action"]
            )
        )


# ============================================================================
# 工具工厂函数
# ============================================================================

def create_todo_tool(mode_manager=None, session_id: Optional[str] = None) -> TodoWriteTool:
    """创建 TodoWrite 工具实例

    Args:
        mode_manager: 模式管理器（可选）
        session_id: 会话 ID（可选）

    Returns:
        TodoWriteTool 实例
    """
    return TodoWriteTool(mode_manager, session_id)


def create_todo_modify_tool(
    mode_manager=None, session_id: Optional[str] = None
) -> TodoModifyTool:
    """创建 TodoModify 工具实例

    Args:
        mode_manager: 模式管理器（可选）
        session_id: 会话 ID（可选）

    Returns:
        TodoModifyTool 实例
    """
    return TodoModifyTool(mode_manager, session_id)
