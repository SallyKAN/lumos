"""
WebSocket 连接管理器

管理 WebSocket 连接、消息广播和会话关联。
"""

import asyncio
import logging
from typing import Dict, Set, Optional, Any
from dataclasses import dataclass, field
from datetime import datetime
import uuid

from fastapi import WebSocket

from .protocol import (
    WebSocketMessage,
    MessageType,
    create_connection_ack_message,
    create_processing_status_message,
)
from .formatters import get_tool_formatter


logger = logging.getLogger(__name__)


def _normalize_tool_result_payload(event_data: Any) -> Dict[str, Any]:
    """标准化工具结果为 WebSocket payload。

    提取工具结果信息并使用格式化器生成摘要。
    """
    tool_name = None
    tool_call_id = None
    success = None
    result = None

    if isinstance(event_data, dict):
        data = event_data.get("tool_result", event_data)
        if isinstance(data, dict):
            tool_name = data.get("tool_name") or data.get("name")
            tool_call_id = data.get("tool_call_id") or data.get("toolCallId")
            if "success" in data:
                success = bool(data.get("success"))
            elif "status" in data:
                success = data.get("status") != "error"
            if "result" in data:
                result = data.get("result")
            elif "data" in data:
                result = data.get("data")
            elif "error" in data:
                result = data.get("error")
        else:
            result = data
    else:
        if hasattr(event_data, "tool_call_id"):
            tool_call_id = getattr(event_data, "tool_call_id")
        if hasattr(event_data, "tool_name"):
            tool_name = getattr(event_data, "tool_name")
        if hasattr(event_data, "success"):
            success = bool(getattr(event_data, "success"))
        elif hasattr(event_data, "status"):
            success = getattr(event_data, "status") != "error"
        if hasattr(event_data, "data"):
            result = getattr(event_data, "data")
        elif hasattr(event_data, "error"):
            result = getattr(event_data, "error")
        else:
            result = event_data

    if result is None:
        result = str(event_data)
    if success is None:
        success = True

    # 使用格式化器生成摘要
    formatter = get_tool_formatter()
    formatted = formatter.format_tool_result(
        tool_name=tool_name or "unknown",
        result=str(result),
        success=success,
        tool_call_id=tool_call_id
    )

    payload = {
        "result": str(result),
        "success": success,
        "summary": formatted.summary,
    }
    if tool_name:
        payload["tool_name"] = tool_name
    if tool_call_id:
        payload["tool_call_id"] = tool_call_id

    return payload


def _normalize_tool_call_payload(event_data: Any) -> Dict[str, Any]:
    """标准化工具调用为 WebSocket payload。

    提取工具调用信息并使用格式化器生成描述。
    """
    tool_id = None
    tool_name = None
    arguments = {}

    if isinstance(event_data, dict):
        data = event_data.get("tool_call", event_data)
        if isinstance(data, dict):
            tool_id = data.get("id") or data.get("tool_call_id")
            tool_name = data.get("name") or data.get("tool_name")
            arguments = data.get("arguments", {})
            if isinstance(arguments, str):
                try:
                    import json
                    arguments = json.loads(arguments)
                except (json.JSONDecodeError, TypeError):
                    arguments = {"raw": arguments}
        else:
            tool_name = str(data)
    else:
        if hasattr(event_data, "id"):
            tool_id = getattr(event_data, "id")
        if hasattr(event_data, "name"):
            tool_name = getattr(event_data, "name")
        if hasattr(event_data, "arguments"):
            arguments = getattr(event_data, "arguments")

    if tool_id is None:
        tool_id = f"tool-{uuid.uuid4().hex[:8]}"
    if tool_name is None:
        tool_name = "unknown"

    # 使用格式化器生成描述
    formatter = get_tool_formatter()
    formatted = formatter.format_tool_call(
        tool_id=tool_id,
        tool_name=tool_name,
        arguments=arguments
    )

    return {
        "id": tool_id,
        "name": tool_name,
        "arguments": arguments,
        "description": formatted.description,
        "formatted_args": formatted.formatted_args,
    }


@dataclass
class ClientConnection:
    """客户端连接信息"""
    connection_id: str
    websocket: WebSocket
    session_id: str
    connected_at: str = field(default_factory=lambda: datetime.now().isoformat())
    last_heartbeat: str = field(default_factory=lambda: datetime.now().isoformat())
    is_processing: bool = False

    def update_heartbeat(self):
        """更新心跳时间"""
        self.last_heartbeat = datetime.now().isoformat()

    def __hash__(self):
        """使用 connection_id 作为哈希值，支持在 Set 中使用"""
        return hash(self.connection_id)

    def __eq__(self, other):
        """基于 connection_id 判断相等性"""
        if isinstance(other, ClientConnection):
            return self.connection_id == other.connection_id
        return False


class WebSocketManager:
    """WebSocket 连接管理器

    管理所有 WebSocket 连接，支持：
    - 多会话管理
    - 同一会话多标签页（多连接）
    - 消息广播
    - 心跳检测
    """

    def __init__(self):
        # session_id -> Set[ClientConnection]（支持多标签页）
        self._connections: Dict[str, Set[ClientConnection]] = {}
        # connection_id -> ClientConnection（快速查找）
        self._connection_map: Dict[str, ClientConnection] = {}
        # 锁，保证线程安全
        self._lock = asyncio.Lock()

    async def connect(
        self,
        websocket: WebSocket,
        session_id: str,
        mode: str = "BUILD",
        tools: Optional[list] = None
    ) -> ClientConnection:
        """建立 WebSocket 连接

        Args:
            websocket: WebSocket 连接对象
            session_id: 会话 ID
            mode: 当前模式
            tools: 可用工具列表

        Returns:
            ClientConnection 对象
        """
        await websocket.accept()

        connection_id = str(uuid.uuid4())
        connection = ClientConnection(
            connection_id=connection_id,
            websocket=websocket,
            session_id=session_id
        )

        async with self._lock:
            # 添加到会话连接集合
            if session_id not in self._connections:
                self._connections[session_id] = set()
            self._connections[session_id].add(connection)

            # 添加到快速查找映射
            self._connection_map[connection_id] = connection

        # 发送连接确认消息
        ack_message = create_connection_ack_message(
            session_id=session_id,
            mode=mode,
            tools=tools or []
        )
        await self.send_to_connection(connection, ack_message)

        logger.info(f"WebSocket connected: session={session_id}, connection={connection_id}")
        return connection

    async def disconnect(self, connection: ClientConnection):
        """断开 WebSocket 连接

        Args:
            connection: 要断开的连接
        """
        async with self._lock:
            session_id = connection.session_id
            connection_id = connection.connection_id

            # 从会话连接集合移除
            if session_id in self._connections:
                self._connections[session_id].discard(connection)
                # 如果会话没有连接了，清理
                if not self._connections[session_id]:
                    del self._connections[session_id]

            # 从快速查找映射移除
            if connection_id in self._connection_map:
                del self._connection_map[connection_id]

        logger.info(f"WebSocket disconnected: session={connection.session_id}, connection={connection.connection_id}")

    async def send_to_connection(
        self,
        connection: ClientConnection,
        message: WebSocketMessage
    ):
        """发送消息到指定连接

        Args:
            connection: 目标连接
            message: 要发送的消息
        """
        try:
            await connection.websocket.send_text(message.to_json())
        except Exception as e:
            logger.error(f"Failed to send message to connection {connection.connection_id}: {e}")
            # 连接可能已断开，尝试清理
            await self.disconnect(connection)

    async def broadcast_to_session(
        self,
        session_id: str,
        message: WebSocketMessage
    ):
        """广播消息到会话的所有连接

        Args:
            session_id: 会话 ID
            message: 要广播的消息
        """
        async with self._lock:
            connections = self._connections.get(session_id, set()).copy()

        if not connections:
            logger.warning(f"No connections for session {session_id}")
            return

        # 并发发送到所有连接
        tasks = [
            self.send_to_connection(conn, message)
            for conn in connections
        ]
        await asyncio.gather(*tasks, return_exceptions=True)

    async def broadcast_agent_event(
        self,
        session_id: str,
        event_type: str,
        event_data: Any
    ):
        """广播 Agent 事件到会话

        将 AgentEvent 转换为 WebSocket 消息并广播

        Args:
            session_id: 会话 ID
            event_type: 事件类型（对应 AgentEvent.type）
            event_data: 事件数据（对应 AgentEvent.data）
        """
        # 映射 AgentEvent 类型到 WebSocket 消息类型
        type_mapping = {
            "thinking": MessageType.THINKING,
            "content_chunk": MessageType.CONTENT_CHUNK,
            "content": MessageType.CONTENT,
            "media_content": MessageType.MEDIA_CONTENT,
            "tool_call": MessageType.TOOL_CALL,
            "tool_result": MessageType.TOOL_RESULT,
            "error": MessageType.ERROR,
            "mode_change": MessageType.MODE_CHANGE,
        }

        msg_type = type_mapping.get(event_type)
        if not msg_type:
            logger.warning(f"Unknown event type: {event_type}")
            return

        # 构建 payload
        if event_type == "content_chunk":
            payload = {"content": event_data}
        elif event_type == "content":
            payload = {"content": event_data}
        elif event_type == "media_content":
            # 媒体内容事件，直接使用 event_data（已包含 content 和 media_items）
            payload = event_data if isinstance(event_data, dict) else {"data": event_data}
        elif event_type == "tool_call":
            payload = _normalize_tool_call_payload(event_data)
        elif event_type == "tool_result":
            payload = _normalize_tool_result_payload(event_data)
        elif event_type == "error":
            payload = {"error": str(event_data)}
        elif event_type == "thinking":
            payload = {"thinking": True}
        elif event_type == "mode_change":
            if isinstance(event_data, dict):
                payload = event_data
            else:
                payload = {"mode": str(event_data)}
        else:
            payload = {"data": event_data}

        message = WebSocketMessage(
            type=msg_type,
            payload=payload,
            session_id=session_id
        )

        await self.broadcast_to_session(session_id, message)

    async def set_processing_status(
        self,
        session_id: str,
        is_processing: bool,
        current_task: Optional[str] = None
    ):
        """设置会话的处理状态

        Args:
            session_id: 会话 ID
            is_processing: 是否正在处理
            current_task: 当前任务描述
        """
        # 更新所有连接的处理状态
        async with self._lock:
            connections = self._connections.get(session_id, set())
            for conn in connections:
                conn.is_processing = is_processing

        # 广播状态变更
        message = create_processing_status_message(
            is_processing=is_processing,
            current_task=current_task,
            session_id=session_id
        )
        await self.broadcast_to_session(session_id, message)

    def get_connection(self, connection_id: str) -> Optional[ClientConnection]:
        """获取连接对象

        Args:
            connection_id: 连接 ID

        Returns:
            ClientConnection 或 None
        """
        return self._connection_map.get(connection_id)

    def get_session_connections(self, session_id: str) -> Set[ClientConnection]:
        """获取会话的所有连接

        Args:
            session_id: 会话 ID

        Returns:
            连接集合
        """
        return self._connections.get(session_id, set()).copy()

    def get_active_sessions(self) -> Set[str]:
        """获取所有活跃会话 ID

        Returns:
            会话 ID 集合
        """
        return set(self._connections.keys())

    def is_session_processing(self, session_id: str) -> bool:
        """检查会话是否正在处理

        Args:
            session_id: 会话 ID

        Returns:
            是否正在处理
        """
        connections = self._connections.get(session_id, set())
        return any(conn.is_processing for conn in connections)

    async def handle_heartbeat(self, connection: ClientConnection):
        """处理心跳

        Args:
            connection: 连接对象
        """
        connection.update_heartbeat()
        # 回复心跳
        message = WebSocketMessage(
            type=MessageType.HEARTBEAT,
            payload={"timestamp": datetime.now().isoformat()},
            session_id=connection.session_id
        )
        await self.send_to_connection(connection, message)

    async def cleanup_stale_connections(self, timeout_seconds: int = 60):
        """清理过期连接

        Args:
            timeout_seconds: 超时秒数
        """
        now = datetime.now()
        stale_connections = []

        async with self._lock:
            for conn in self._connection_map.values():
                last_heartbeat = datetime.fromisoformat(conn.last_heartbeat)
                if (now - last_heartbeat).total_seconds() > timeout_seconds:
                    stale_connections.append(conn)

        for conn in stale_connections:
            logger.info(f"Cleaning up stale connection: {conn.connection_id}")
            try:
                await conn.websocket.close()
            except Exception:
                pass
            await self.disconnect(conn)


# 全局单例
_manager: Optional[WebSocketManager] = None


def get_websocket_manager() -> WebSocketManager:
    """获取 WebSocket 管理器单例"""
    global _manager
    if _manager is None:
        _manager = WebSocketManager()
    return _manager
