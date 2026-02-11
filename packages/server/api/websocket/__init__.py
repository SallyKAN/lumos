"""
WebSocket 模块

提供 WebSocket 连接管理和消息协议。
"""

from .protocol import (
    MessageType,
    InterruptIntent,
    TodoAction,
    SessionAction,
    WebSocketMessage,
    ChatMessagePayload,
    ToolCallPayload,
    ToolResultPayload,
    InterruptPayload,
    InterruptResultPayload,
    TodoUpdatePayload,
    SessionUpdatePayload,
    ModeChangePayload,
    ProcessingStatusPayload,
    ConnectionAckPayload,
    ErrorPayload,
    create_message,
    create_content_chunk_message,
    create_tool_call_message,
    create_tool_result_message,
    create_error_message,
    create_todo_update_message,
    create_mode_change_message,
    create_processing_status_message,
    create_connection_ack_message,
    create_interrupt_result_message,
)

from .manager import (
    ClientConnection,
    WebSocketManager,
    get_websocket_manager,
)

__all__ = [
    # Protocol
    "MessageType",
    "InterruptIntent",
    "TodoAction",
    "SessionAction",
    "WebSocketMessage",
    "ChatMessagePayload",
    "ToolCallPayload",
    "ToolResultPayload",
    "InterruptPayload",
    "InterruptResultPayload",
    "TodoUpdatePayload",
    "SessionUpdatePayload",
    "ModeChangePayload",
    "ProcessingStatusPayload",
    "ConnectionAckPayload",
    "ErrorPayload",
    "create_message",
    "create_content_chunk_message",
    "create_tool_call_message",
    "create_tool_result_message",
    "create_error_message",
    "create_todo_update_message",
    "create_mode_change_message",
    "create_processing_status_message",
    "create_connection_ack_message",
    "create_interrupt_result_message",
    # Manager
    "ClientConnection",
    "WebSocketManager",
    "get_websocket_manager",
]
