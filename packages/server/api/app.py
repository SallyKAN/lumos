"""
FastAPI 应用工厂

创建和配置 FastAPI 应用，包括：
- REST API 路由
- WebSocket 端点
- CORS 配置
- 静态文件服务
"""

import asyncio
from contextlib import asynccontextmanager
import json
import logging
import os
from typing import Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .routes import (
    sessions_router,
    todos_router,
    chat_router,
    skills_router,
    tts_router,
)
from .websocket import (
    get_websocket_manager,
    WebSocketMessage,
    MessageType,
    create_error_message,
    create_interrupt_result_message,
)
from .services import get_agent_service


logger = logging.getLogger(__name__)
_DEFAULT_SSL_VERIFY = "false"


def _ensure_ssl_verify_default() -> None:
    """保证 LLM_SSL_VERIFY 有默认值，避免证书配置错误。"""
    if "LLM_SSL_VERIFY" not in os.environ:
        os.environ["LLM_SSL_VERIFY"] = _DEFAULT_SSL_VERIFY


# ============================================================================
# 应用生命周期
# ============================================================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    # 启动时
    logger.info("Starting Lumos Code Web API...")
    yield
    # 关闭时
    logger.info("Shutting down Lumos Code Web API...")


# ============================================================================
# 应用工厂
# ============================================================================

def create_app(
    title: str = "Lumos Code API",
    version: str = "0.1.0",
    debug: bool = False,
    cors_origins: Optional[list] = None
) -> FastAPI:
    """创建 FastAPI 应用

    Args:
        title: API 标题
        version: API 版本
        debug: 是否开启调试模式
        cors_origins: CORS 允许的源列表

    Returns:
        FastAPI 应用实例
    """
    _ensure_ssl_verify_default()

    app = FastAPI(
        title=title,
        version=version,
        description="Lumos Code - AI 助手 Web API",
        debug=debug,
        lifespan=lifespan
    )

    # 配置 CORS
    origins = cors_origins or [
        "http://localhost:3000",
        "http://localhost:5173",
        "http://127.0.0.1:3000",
        "http://127.0.0.1:5173",
    ]

    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # 注册 REST API 路由
    app.include_router(sessions_router, prefix="/api")
    app.include_router(todos_router, prefix="/api")
    app.include_router(chat_router, prefix="/api")
    app.include_router(skills_router, prefix="/api")
    app.include_router(tts_router, prefix="/api")

    # 挂载媒体静态文件目录
    media_base_dir = os.path.expanduser(
        os.getenv("MEDIA_OUTPUT_DIR", "~/.lumos/media")
    )
    os.makedirs(media_base_dir, exist_ok=True)
    app.mount("/api/media", StaticFiles(directory=media_base_dir), name="media")
    logger.info(f"Media static files mounted at /api/media -> {media_base_dir}")

    # 注册 WebSocket 端点
    register_websocket_endpoints(app)

    # 健康检查端点
    @app.get("/health")
    async def health_check():
        return {"status": "healthy", "version": version}

    # API 信息端点
    @app.get("/api/info")
    async def api_info():
        return {
            "name": title,
            "version": version,
            "endpoints": {
                "rest": [
                    "/api/sessions",
                    "/api/todos",
                    "/api/chat",
                    "/api/skills"
                ],
                "websocket": "/ws/{session_id}"
            }
        }

    # 配置端点 - 返回默认配置（用于前端）
    @app.get("/api/config")
    async def get_config():
        """获取默认配置
        
        从配置文件和环境变量读取默认的 provider 等配置，
        供前端在初始化时使用。
        """
        agent_service = get_agent_service()
        provider, api_key, api_base, model = agent_service._get_config()
        
        return {
            "provider": provider,
            "model": model,
            "api_base": api_base,
            "has_api_key": bool(api_key),
        }

    return app


# ============================================================================
# WebSocket 端点
# ============================================================================

def register_websocket_endpoints(app: FastAPI):
    """注册 WebSocket 端点"""

    @app.websocket("/ws/{session_id}")
    async def websocket_endpoint(
        websocket: WebSocket,
        session_id: str,
        provider: str = Query("openai", description="模型提供商"),
        api_key: Optional[str] = Query(None, description="API 密钥"),
        api_base: Optional[str] = Query(None, description="API Base URL"),
        model: Optional[str] = Query(None, description="模型名称"),
        project_path: Optional[str] = Query(None, description="项目路径")
    ):
        """WebSocket 连接端点

        连接后会自动创建或恢复 Agent 会话。
        """
        ws_manager = get_websocket_manager()
        agent_service = get_agent_service()

        try:
            # 获取或创建 Agent 会话
            session = await agent_service.get_or_create_session(
                session_id=session_id if session_id != "new" else None,
                provider=provider,
                api_key=api_key,
                api_base=api_base,
                model=model,
                project_path=project_path
            )

            # 建立 WebSocket 连接
            connection = await ws_manager.connect(
                websocket=websocket,
                session_id=session.session_id,
                mode=session.mode_manager.get_current_mode().value,
                tools=session.agent.get_available_tools()
            )

            # 消息处理循环
            while True:
                try:
                    # 接收消息
                    data = await websocket.receive_text()
                    message = WebSocketMessage.from_json(data)

                    # 处理消息
                    await handle_websocket_message(
                        connection=connection,
                        message=message,
                        session=session,
                        ws_manager=ws_manager,
                        agent_service=agent_service
                    )

                except WebSocketDisconnect:
                    logger.info(f"WebSocket disconnected: {connection.connection_id}")
                    break
                except json.JSONDecodeError as e:
                    logger.error(f"Invalid JSON: {e}")
                    error_msg = create_error_message(
                        "Invalid message format",
                        code="INVALID_JSON",
                        session_id=session.session_id
                    )
                    await ws_manager.send_to_connection(connection, error_msg)
                except Exception as e:
                    logger.error(f"Error handling message: {e}")
                    error_msg = create_error_message(
                        str(e),
                        code="HANDLER_ERROR",
                        session_id=session.session_id
                    )
                    await ws_manager.send_to_connection(connection, error_msg)

        except Exception as e:
            logger.error(f"WebSocket error: {e}")
            # 尝试发送错误消息
            try:
                await websocket.accept()
                await websocket.send_text(
                    create_error_message(str(e), code="CONNECTION_ERROR").to_json()
                )
                await websocket.close()
            except Exception:
                pass

        finally:
            # 清理正在运行的任务
            if 'session' in locals() and session is not None:
                if (
                    session._current_process_task
                    and not session._current_process_task.done()
                ):
                    session._current_process_task.cancel()
                    try:
                        await session._current_process_task
                    except asyncio.CancelledError:
                        pass

            # 清理连接
            if 'connection' in locals() and connection is not None:
                await ws_manager.disconnect(connection)


async def _run_process_message(
    agent_service,
    session,
    session_id: str,
    content: str,
    conversation_id: str
):
    """在后台 Task 中运行消息处理

    Args:
        agent_service: Agent 服务
        session: Agent 会话
        session_id: 会话 ID
        content: 消息内容
        conversation_id: 对话 ID
    """
    try:
        async for event in agent_service.process_message(
            session_id=session_id,
            message=content,
            conversation_id=conversation_id
        ):
            # 事件已在 process_message 中广播
            pass
    except asyncio.CancelledError:
        logger.info(f"Message processing cancelled for session {session_id}")
        # 广播取消消息
        from .websocket.protocol import create_content_chunk_message
        ws_manager = get_websocket_manager()
        await ws_manager.broadcast_to_session(
            session_id,
            create_content_chunk_message("\n\n[任务已中断]", session_id)
        )
    finally:
        # 清理 Task 引用
        session._current_process_task = None


async def handle_websocket_message(
    connection,
    message: WebSocketMessage,
    session,
    ws_manager,
    agent_service
):
    """处理 WebSocket 消息

    Args:
        connection: WebSocket 连接
        message: 接收到的消息
        session: Agent 会话
        ws_manager: WebSocket 管理器
        agent_service: Agent 服务
    """
    msg_type = message.type
    payload = message.payload
    session_id = session.session_id

    if msg_type == MessageType.CHAT_MESSAGE:
        # 处理聊天消息
        content = payload.get("content", "")
        # 使用 session_id 作为默认的 conversation_id，确保每个会话有独立的对话历史
        conversation_id = payload.get("conversation_id", session_id)

        if not content:
            error_msg = create_error_message(
                "Empty message content",
                code="EMPTY_MESSAGE",
                session_id=session_id
            )
            await ws_manager.send_to_connection(connection, error_msg)
            return

        # 如果有正在运行的任务，先取消它
        if session._current_process_task and not session._current_process_task.done():
            session._current_process_task.cancel()
            try:
                await session._current_process_task
            except asyncio.CancelledError:
                pass

        # 创建后台 Task 处理消息（不阻塞 WebSocket 消息循环）
        task = asyncio.create_task(
            _run_process_message(
                agent_service, session, session_id, content, conversation_id
            )
        )
        session._current_process_task = task
        # 不等待任务完成，让 WebSocket 循环可以继续接收中断消息

    elif msg_type == MessageType.INTERRUPT:
        # 处理中断 - 使用意图识别
        new_input = payload.get("new_input")
        explicit_intent = payload.get("intent")  # 可选的显式意图（如 pause）

        # 如果有正在运行的任务，取消它
        if session._current_process_task and not session._current_process_task.done():
            session.request_cancel()  # 设置取消标志
            session._current_process_task.cancel()  # 取消任务
            try:
                await asyncio.wait_for(
                    session._current_process_task, timeout=2.0
                )
            except (asyncio.CancelledError, asyncio.TimeoutError):
                pass
            session._current_process_task = None

        result = await agent_service.handle_interrupt(
            session_id=session_id,
            new_input=new_input,
            explicit_intent=explicit_intent
        )

        # 发送中断结果
        response = create_interrupt_result_message(
            intent=result.get("intent", "cancel"),
            success=result.get("success", True),
            message=result.get("message", ""),
            new_input=result.get("new_input"),
            merged_input=result.get("merged_input"),
            paused_task=result.get("paused_task"),
            session_id=session_id
        )
        await ws_manager.send_to_connection(connection, response)

        # 如果意图是 switch 且有新输入，启动新任务处理
        if result.get("intent") == "switch" and result.get("new_input"):
            task = asyncio.create_task(
                _run_process_message(
                    agent_service, session, session_id,
                    result["new_input"], "default"
                )
            )
            session._current_process_task = task
            # 不等待，让 WebSocket 循环继续

        # 如果意图是 supplement 且有合并输入，继续处理
        elif result.get("intent") == "supplement" and result.get("merged_input"):
            task = asyncio.create_task(
                _run_process_message(
                    agent_service, session, session_id,
                    result["merged_input"], "default"
                )
            )
            session._current_process_task = task
            # 不等待，让 WebSocket 循环继续

        # 如果意图是 resume，启动任务处理
        # 优先使用 merged_input（包含恢复上下文），否则使用 new_input
        elif result.get("intent") == "resume":
            resume_input = result.get("merged_input") or new_input
            if resume_input:
                task = asyncio.create_task(
                    _run_process_message(
                        agent_service, session, session_id,
                        resume_input, "default"
                    )
                )
                session._current_process_task = task
                # 不等待，让 WebSocket 循环继续

    elif msg_type == MessageType.SWITCH_MODE:
        # 切换模式
        mode = payload.get("mode", "BUILD")
        success = agent_service.switch_mode(session_id, mode)

        if success:
            from .websocket.protocol import create_mode_change_message
            msg = create_mode_change_message(
                mode=mode.upper(),
                session_id=session_id
            )
            await ws_manager.broadcast_to_session(session_id, msg)
        else:
            error_msg = create_error_message(
                f"Failed to switch to mode: {mode}",
                code="MODE_SWITCH_ERROR",
                session_id=session_id
            )
            await ws_manager.send_to_connection(connection, error_msg)

    elif msg_type == MessageType.TODO_ACTION:
        # Todo 操作
        action = payload.get("action")

        if action == "list":
            todos = agent_service.get_todos(session_id)
            from .websocket.protocol import create_todo_update_message
            msg = create_todo_update_message(todos, session_id)
            await ws_manager.send_to_connection(connection, msg)

        elif action == "update":
            task_id = payload.get("task_id")
            status = payload.get("status")
            if task_id and status:
                await agent_service.update_todo(session_id, task_id, status)

    elif msg_type == MessageType.SKILL_ACTION:
        # Skill 操作
        action = payload.get("action")
        spec = payload.get("spec")
        force = payload.get("force", False)

        await agent_service.handle_skill_action(
            session_id=session_id,
            action=action,
            spec=spec,
            force=force
        )

    elif msg_type == MessageType.HEARTBEAT:
        # 心跳
        await ws_manager.handle_heartbeat(connection)

    elif msg_type == MessageType.USER_ANSWER:
        # 用户回答（用于 ask_user_question 工具）
        request_id = payload.get("request_id")
        answers = payload.get("answers", [])

        if request_id:
            # 导入并调用 receive_user_answer 函数
            from ..tools.user_interaction_tools import receive_user_answer
            receive_user_answer(request_id, answers)
            logger.info(f"Received user answer for request: {request_id}")

    else:
        logger.warning(f"Unknown message type: {msg_type}")


# ============================================================================
# 应用入口
# ============================================================================

# 创建默认应用实例
app = create_app()


def main():
    """运行应用"""
    import uvicorn

    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "8000"))
    debug = os.getenv("DEBUG", "false").lower() == "true"

    uvicorn.run(
        "packages.server.api.app:app",
        host=host,
        port=port,
        reload=debug,
        log_level="info" if not debug else "debug"
    )


if __name__ == "__main__":
    main()
