"""
会话管理 REST API 路由
"""

import os
from typing import Optional, List
from fastapi import APIRouter, HTTPException, Query, Path
from pydantic import BaseModel

from ..services import get_session_service


router = APIRouter(prefix="/sessions", tags=["sessions"])


# ============================================================================
# 请求/响应模型
# ============================================================================

class CreateSessionRequest(BaseModel):
    """创建会话请求"""
    project_path: str
    title: Optional[str] = None


class UpdateSessionRequest(BaseModel):
    """更新会话请求"""
    title: Optional[str] = None
    status: Optional[str] = None


class SessionResponse(BaseModel):
    """会话响应"""
    session_id: str
    title: str
    project_path: str
    mode: str
    status: str
    message_count: int
    created_at: str
    updated_at: str
    tags: List[str] = []


class SessionListResponse(BaseModel):
    """会话列表响应"""
    sessions: List[SessionResponse]
    total: int


# ============================================================================
# 路由
# ============================================================================

@router.post("", response_model=SessionResponse)
async def create_session(request: CreateSessionRequest):
    """创建新会话"""
    service = get_session_service()
    result = service.create_session(
        project_path=request.project_path,
        title=request.title
    )
    return SessionResponse(**result)


@router.get("", response_model=SessionListResponse)
async def list_sessions(
    project_path: Optional[str] = Query(None, description="按项目路径过滤"),
    status: Optional[str] = Query(None, description="按状态过滤"),
    limit: int = Query(20, ge=1, le=100, description="返回数量限制")
):
    """列出会话"""
    service = get_session_service()
    sessions = service.list_sessions(
        project_path=project_path,
        status=status,
        limit=limit
    )
    return SessionListResponse(
        sessions=[SessionResponse(**s) for s in sessions],
        total=len(sessions)
    )


@router.get("/search")
async def search_sessions(
    q: str = Query(..., description="搜索关键词"),
    limit: int = Query(10, ge=1, le=50, description="返回数量限制")
):
    """搜索会话"""
    service = get_session_service()
    sessions = service.search_sessions(q, limit)
    return {
        "sessions": sessions,
        "total": len(sessions)
    }


@router.get("/recent")
async def get_recent_sessions(
    limit: int = Query(5, ge=1, le=20, description="返回数量限制")
):
    """获取最近的会话"""
    service = get_session_service()
    sessions = service.get_recent_sessions(limit)
    return {
        "sessions": sessions,
        "total": len(sessions)
    }


@router.get("/{session_id}")
async def get_session(session_id: str):
    """获取会话详情"""
    service = get_session_service()
    result = service.get_session(session_id)
    if not result:
        raise HTTPException(status_code=404, detail="Session not found")
    return result


@router.patch("/{session_id}")
async def update_session(session_id: str, request: UpdateSessionRequest):
    """更新会话"""
    service = get_session_service()
    result = service.update_session(
        session_id=session_id,
        title=request.title,
        status=request.status
    )
    if not result:
        raise HTTPException(status_code=404, detail="Session not found")
    return result


@router.delete("/{session_id}")
async def delete_session(session_id: str):
    """删除会话"""
    service = get_session_service()
    success = service.delete_session(session_id)
    if not success:
        raise HTTPException(status_code=404, detail="Session not found")
    return {"success": True, "session_id": session_id}


@router.post("/{session_id}/pause")
async def pause_session(session_id: str):
    """暂停会话"""
    service = get_session_service()
    success = service.pause_session(session_id)
    if not success:
        raise HTTPException(status_code=404, detail="Session not found")
    return {"success": True, "session_id": session_id, "status": "paused"}


@router.post("/{session_id}/resume")
async def resume_session(session_id: str):
    """恢复会话"""
    service = get_session_service()
    success = service.resume_session(session_id)
    if not success:
        raise HTTPException(status_code=404, detail="Session not found")
    return {"success": True, "session_id": session_id, "status": "active"}


@router.get("/{session_id}/messages")
async def get_session_messages(
    session_id: str,
    limit: int = Query(100, ge=1, le=500, description="最大返回消息数")
):
    """获取会话消息历史"""
    service = get_session_service()
    messages = service.get_messages(session_id, limit)
    return {"messages": messages, "total": len(messages)}


@router.get("/{session_id}/offload-files")
async def list_session_offload_files(session_id: str):
    """获取指定会话的离线消息文件列表"""
    service = get_session_service()
    try:
        files = service.list_offload_files(session_id)
    except ValueError as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    base_dir = os.environ.get("OFFLOAD_MESSAGE_DIR", ".lumos")
    path = os.path.join(base_dir, session_id)
    return {"session_id": session_id, "files": files, "path": path, "total": len(files)}


@router.get("/{session_id}/offload-files/{filename}")
async def read_session_offload_file(
    session_id: str,
    filename: str = Path(..., description="离线文件名")
):
    """读取指定会话的离线消息文件内容"""
    service = get_session_service()
    try:
        content = service.read_offload_file(session_id, filename)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    base_dir = os.environ.get("OFFLOAD_MESSAGE_DIR", ".lumos")
    file_path = os.path.join(base_dir, session_id, filename)
    return {
        "session_id": session_id,
        "filename": filename,
        "content": content,
        "path": file_path
    }
