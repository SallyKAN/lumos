"""
会话服务层

提供会话管理的 Web API 接口。
"""

import logging
import os
from pathlib import Path
from typing import Dict, Any, Optional, List

from ...session.session_manager import SessionManager, SessionMetadata


logger = logging.getLogger(__name__)


class SessionService:
    """会话服务

    封装 SessionManager，提供 Web API 友好的接口。
    """

    def __init__(self):
        self._session_manager = SessionManager()

    def create_session(
        self,
        project_path: str,
        title: Optional[str] = None
    ) -> Dict[str, Any]:
        """创建新会话

        Args:
            project_path: 项目路径
            title: 会话标题

        Returns:
            会话信息
        """
        session_id = self._session_manager.create_session(project_path, title or "")

        metadata, _, _ = self._session_manager.load_session(session_id)
        if metadata:
            return self._metadata_to_dict(metadata)

        return {"session_id": session_id, "project_path": project_path}

    def get_session(self, session_id: str) -> Optional[Dict[str, Any]]:
        """获取会话信息

        Args:
            session_id: 会话 ID

        Returns:
            会话信息或 None
        """
        metadata, summary, todos = self._session_manager.load_session(session_id)
        if not metadata:
            return None

        result = self._metadata_to_dict(metadata)
        if summary:
            result["summary"] = {
                "context": summary.context,
                "key_decisions": summary.key_decisions,
                "modified_files": summary.modified_files,
                "last_action": summary.last_action,
                "interrupted_task": summary.interrupted_task
            }
        result["todos"] = [t.to_dict() for t in todos]

        return result

    def list_sessions(
        self,
        project_path: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 20
    ) -> List[Dict[str, Any]]:
        """列出会话

        Args:
            project_path: 按项目路径过滤
            status: 按状态过滤
            limit: 返回数量限制

        Returns:
            会话列表
        """
        sessions = self._session_manager.list_sessions(
            project_path=project_path,
            status=status,
            limit=limit
        )
        return [self._metadata_to_dict(s) for s in sessions]

    def search_sessions(self, query: str, limit: int = 10) -> List[Dict[str, Any]]:
        """搜索会话

        Args:
            query: 搜索关键词
            limit: 返回数量限制

        Returns:
            匹配的会话列表
        """
        sessions = self._session_manager.search_sessions(query, limit)
        return [self._metadata_to_dict(s) for s in sessions]

    def update_session(
        self,
        session_id: str,
        title: Optional[str] = None,
        status: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """更新会话

        Args:
            session_id: 会话 ID
            title: 新标题
            status: 新状态

        Returns:
            更新后的会话信息或 None
        """
        if title:
            self._session_manager.update_title(session_id, title)
        if status:
            self._session_manager.update_status(session_id, status)

        return self.get_session(session_id)

    def delete_session(self, session_id: str) -> bool:
        """删除会话

        Args:
            session_id: 会话 ID

        Returns:
            是否成功
        """
        return self._session_manager.delete_session(session_id)

    def pause_session(self, session_id: str) -> bool:
        """暂停会话

        Args:
            session_id: 会话 ID

        Returns:
            是否成功
        """
        return self._session_manager.update_status(session_id, "paused")

    def resume_session(self, session_id: str) -> bool:
        """恢复会话

        Args:
            session_id: 会话 ID

        Returns:
            是否成功
        """
        return self._session_manager.update_status(session_id, "active")

    def get_recent_sessions(self, limit: int = 5) -> List[Dict[str, Any]]:
        """获取最近的会话

        Args:
            limit: 返回数量限制

        Returns:
            最近的会话列表
        """
        sessions = self._session_manager.get_recent_sessions(limit)
        return [self._metadata_to_dict(s) for s in sessions]

    def list_offload_files(self, session_id: str) -> List[str]:
        """列出指定会话的离线消息文件名

        会从环境变量 OFFLOAD_MESSAGE_DIR 指定的目录下读取
        以会话 ID 为子目录名、扩展名为 .offload 的文件列表。

        Args:
            session_id: 会话 ID

        Returns:
            文件名列表（仅文件名，不含路径），按名称排序

        Raises:
            ValueError: 当 OFFLOAD_MESSAGE_DIR 未设置时
        """
        base_dir = os.environ.get("OFFLOAD_MESSAGE_DIR", ".lumos")
        if not base_dir:
            raise ValueError("OFFLOAD_MESSAGE_DIR is not set")

        session_dir = Path(base_dir) / session_id
        if not session_dir.exists():
            return []

        files = [
            path.name
            for path in session_dir.glob("*.offload")
            if path.is_file()
        ]
        return sorted(files)

    def read_offload_file(self, session_id: str, filename: str) -> str:
        """读取指定会话的离线消息文件内容

        Args:
            session_id: 会话 ID
            filename: 离线文件名（必须以 .offload 结尾）

        Returns:
            文件内容

        Raises:
            ValueError: 当 OFFLOAD_MESSAGE_DIR 未设置或文件名非法
            FileNotFoundError: 文件不存在
        """
        base_dir = os.environ.get("OFFLOAD_MESSAGE_DIR", ".lumos")
        if not base_dir:
            raise ValueError("OFFLOAD_MESSAGE_DIR is not set")

        file_name = Path(filename).name
        if file_name != filename or not file_name.endswith(".offload"):
            raise ValueError("Invalid offload filename")

        session_dir = Path(base_dir) / session_id
        file_path = session_dir / file_name
        if not file_path.exists() or not file_path.is_file():
            raise FileNotFoundError("Offload file not found")

        with file_path.open("r", encoding="utf-8", errors="replace") as file_obj:
            return file_obj.read()

    def _metadata_to_dict(self, metadata: SessionMetadata) -> Dict[str, Any]:
        """将 SessionMetadata 转换为字典"""
        return {
            "session_id": metadata.session_id,
            "title": metadata.title,
            "project_path": metadata.project_path,
            "mode": metadata.mode,
            "status": metadata.status,
            "message_count": metadata.message_count,
            "created_at": metadata.created_at,
            "updated_at": metadata.updated_at,
            "tags": metadata.tags
        }

    def get_messages(
        self,
        session_id: str,
        limit: int = 100
    ) -> List[Dict[str, Any]]:
        """获取会话消息历史

        Args:
            session_id: 会话 ID
            limit: 最大返回消息数

        Returns:
            消息列表
        """
        messages = self._session_manager.load_messages(session_id)
        if limit and len(messages) > limit:
            return messages[-limit:]
        return messages


# 全局单例
_service: Optional[SessionService] = None


def get_session_service() -> SessionService:
    """获取会话服务单例"""
    global _service
    if _service is None:
        _service = SessionService()
    return _service
