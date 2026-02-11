"""
Todo 管理 REST API 路由
"""

from typing import Optional, List
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..services import get_agent_service


router = APIRouter(prefix="/todos", tags=["todos"])


# ============================================================================
# 请求/响应模型
# ============================================================================

class TodoItem(BaseModel):
    """Todo 项"""
    id: str
    content: str
    activeForm: str
    status: str
    createdAt: str
    updatedAt: str


class CreateTodosRequest(BaseModel):
    """创建 Todo 请求"""
    tasks: Optional[str] = None  # 简化格式：用分号分隔的任务字符串
    todos: Optional[List[dict]] = None  # 完整格式


class UpdateTodoRequest(BaseModel):
    """更新 Todo 请求"""
    status: str


class TodoListResponse(BaseModel):
    """Todo 列表响应"""
    todos: List[TodoItem]
    total: int


# ============================================================================
# 路由
# ============================================================================

@router.get("/{session_id}", response_model=TodoListResponse)
async def get_todos(session_id: str):
    """获取会话的 Todo 列表"""
    service = get_agent_service()
    todos = service.get_todos(session_id)
    return TodoListResponse(
        todos=[TodoItem(**t) for t in todos],
        total=len(todos)
    )


@router.patch("/{session_id}/{task_id}")
async def update_todo(session_id: str, task_id: str, request: UpdateTodoRequest):
    """更新 Todo 状态"""
    service = get_agent_service()
    result = await service.update_todo(session_id, task_id, request.status)

    if not result.get("success"):
        raise HTTPException(
            status_code=400,
            detail=result.get("error", "Failed to update todo")
        )

    return result
