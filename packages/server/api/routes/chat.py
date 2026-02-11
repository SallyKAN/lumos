"""
聊天 REST API 路由（主要用于非 WebSocket 场景）
"""

from typing import Optional
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..services import get_agent_service


router = APIRouter(prefix="/chat", tags=["chat"])


# ============================================================================
# 请求/响应模型
# ============================================================================

class ChatRequest(BaseModel):
    """聊天请求"""
    message: str
    session_id: Optional[str] = None
    conversation_id: str = "default"
    # LLM 配置（可选，用于创建新会话）
    provider: str = "openai"
    api_key: Optional[str] = None
    api_base: Optional[str] = None
    model: Optional[str] = None
    project_path: Optional[str] = None


class InterruptRequest(BaseModel):
    """中断请求"""
    intent: str  # switch/pause/cancel/supplement
    new_input: Optional[str] = None


class SwitchModeRequest(BaseModel):
    """切换模式请求"""
    mode: str  # BUILD/PLAN/REVIEW


# ============================================================================
# 路由
# ============================================================================

@router.post("/{session_id}/interrupt")
async def interrupt_session(session_id: str, request: InterruptRequest):
    """中断当前处理"""
    service = get_agent_service()
    result = await service.handle_interrupt(
        session_id=session_id,
        intent=request.intent,
        new_input=request.new_input
    )

    if not result.get("success"):
        raise HTTPException(
            status_code=400,
            detail=result.get("error", "Failed to interrupt")
        )

    return result


@router.post("/{session_id}/mode")
async def switch_mode(session_id: str, request: SwitchModeRequest):
    """切换模式"""
    service = get_agent_service()
    success = service.switch_mode(session_id, request.mode)

    if not success:
        raise HTTPException(
            status_code=400,
            detail=f"Failed to switch to mode: {request.mode}"
        )

    return {
        "success": True,
        "session_id": session_id,
        "mode": request.mode.upper()
    }


@router.get("/{session_id}/info")
async def get_session_info(session_id: str):
    """获取会话信息（包括处理状态）"""
    service = get_agent_service()
    info = service.get_session_info(session_id)

    if not info:
        raise HTTPException(status_code=404, detail="Session not found")

    return info
