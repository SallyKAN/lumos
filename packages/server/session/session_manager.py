"""
会话管理器

负责会话的创建、保存、恢复和搜索功能。
支持会话元数据、上下文摘要和任务列表的持久化。

存储结构:
~/.lumos/sessions/
├── {session_id}/
│   ├── metadata.json     # 会话元数据
│   ├── summary.json      # 上下文摘要
│   └── todos.json        # 任务列表
└── index.json            # 会话索引（快速搜索）
"""

import os
import json
import uuid
import shutil
from datetime import datetime
from typing import List, Optional, Tuple, Dict, Any
from pathlib import Path
from dataclasses import dataclass, field, asdict


# ============================================================================
# 数据模型
# ============================================================================

@dataclass
class SessionMetadata:
    """会话元数据"""
    session_id: str
    title: str                              # LLM 自动生成的标题
    project_path: str                       # 项目路径
    created_at: str                         # ISO 格式时间戳
    updated_at: str                         # ISO 格式时间戳
    mode: str = "BUILD"                     # BUILD/PLAN/REVIEW
    status: str = "active"                  # active/paused/completed/interrupted
    message_count: int = 0
    tags: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return asdict(self)

    @staticmethod
    def from_dict(data: Dict[str, Any]) -> 'SessionMetadata':
        """从字典创建实例"""
        return SessionMetadata(
            session_id=data["session_id"],
            title=data.get("title", "未命名会话"),
            project_path=data.get("project_path", ""),
            created_at=data.get("created_at", datetime.now().isoformat()),
            updated_at=data.get("updated_at", datetime.now().isoformat()),
            mode=data.get("mode", "BUILD"),
            status=data.get("status", "active"),
            message_count=data.get("message_count", 0),
            tags=data.get("tags", [])
        )


@dataclass
class SessionSummary:
    """会话上下文摘要"""
    context: str = ""                       # 当前上下文描述
    key_decisions: List[str] = field(default_factory=list)  # 关键决策
    modified_files: List[str] = field(default_factory=list)  # 修改过的文件
    last_action: str = ""                   # 最后执行的操作
    interrupted_task: Optional[str] = None  # 被中断的任务描述

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return asdict(self)

    @staticmethod
    def from_dict(data: Dict[str, Any]) -> 'SessionSummary':
        """从字典创建实例"""
        return SessionSummary(
            context=data.get("context", ""),
            key_decisions=data.get("key_decisions", []),
            modified_files=data.get("modified_files", []),
            last_action=data.get("last_action", ""),
            interrupted_task=data.get("interrupted_task")
        )


@dataclass
class InterruptState:
    """中断状态"""
    task_description: str                   # 被中断任务的描述
    current_todo_id: Optional[str] = None   # 当前执行的 Todo ID
    partial_result: Optional[str] = None    # 部分执行结果
    timestamp: str = ""                     # ISO 格式时间戳

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.now().isoformat()

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return asdict(self)

    @staticmethod
    def from_dict(data: Dict[str, Any]) -> 'InterruptState':
        """从字典创建实例"""
        return InterruptState(
            task_description=data.get("task_description", ""),
            current_todo_id=data.get("current_todo_id"),
            partial_result=data.get("partial_result"),
            timestamp=data.get("timestamp", datetime.now().isoformat())
        )


@dataclass
class TodoItem:
    """待办事项数据模型（与 todo_tools.py 保持一致）"""
    id: str
    content: str
    activeForm: str
    status: str
    createdAt: str
    updatedAt: str

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "id": self.id,
            "content": self.content,
            "activeForm": self.activeForm,
            "status": self.status,
            "createdAt": self.createdAt,
            "updatedAt": self.updatedAt
        }

    @staticmethod
    def from_dict(data: Dict[str, Any]) -> 'TodoItem':
        """从字典创建实例"""
        return TodoItem(
            id=data["id"],
            content=data["content"],
            activeForm=data.get("activeForm", data["content"]),
            status=data["status"],
            createdAt=data.get("createdAt", datetime.now().isoformat()),
            updatedAt=data.get("updatedAt", datetime.now().isoformat())
        )


# ============================================================================
# 会话管理器
# ============================================================================

class SessionManager:
    """会话管理器 - 负责会话的创建、保存、恢复"""

    def __init__(self, sessions_dir: Optional[Path] = None):
        """初始化会话管理器

        Args:
            sessions_dir: 会话存储目录，默认 ~/.lumos/sessions
        """
        self.sessions_dir = sessions_dir or Path.home() / ".lumos" / "sessions"
        self.sessions_dir.mkdir(parents=True, exist_ok=True)
        self.index_file = self.sessions_dir / "index.json"
        self._ensure_index()

    def _ensure_index(self):
        """确保索引文件存在"""
        if not self.index_file.exists():
            self._save_index({})

    def _load_index(self) -> Dict[str, Dict]:
        """加载会话索引"""
        try:
            if self.index_file.exists():
                with open(self.index_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
        except Exception:
            pass
        return {}

    def _save_index(self, index: Dict[str, Dict]) -> bool:
        """保存会话索引"""
        try:
            with open(self.index_file, 'w', encoding='utf-8') as f:
                json.dump(index, f, ensure_ascii=False, indent=2)
            return True
        except Exception:
            return False

    def _update_index(self, metadata: SessionMetadata):
        """更新索引中的会话信息"""
        index = self._load_index()
        index[metadata.session_id] = {
            "title": metadata.title,
            "project_path": metadata.project_path,
            "updated_at": metadata.updated_at,
            "status": metadata.status,
            "mode": metadata.mode
        }
        self._save_index(index)

    def _remove_from_index(self, session_id: str):
        """从索引中移除会话"""
        index = self._load_index()
        if session_id in index:
            del index[session_id]
            self._save_index(index)

    # ========================================================================
    # 会话生命周期
    # ========================================================================

    def generate_session_id(self) -> str:
        """生成会话 ID

        格式: {YYYYMMDD}_{HHMMSS}_{short_uuid}
        例如: 20260203_143052_a1b2c3
        """
        now = datetime.now()
        date_part = now.strftime("%Y%m%d_%H%M%S")
        uuid_part = uuid.uuid4().hex[:6]
        return f"{date_part}_{uuid_part}"

    def create_session(self, project_path: str, title: str = "") -> str:
        """创建新会话

        Args:
            project_path: 项目路径
            title: 会话标题（可选，默认自动生成）

        Returns:
            新会话的 ID
        """
        session_id = self.generate_session_id()
        session_dir = self.sessions_dir / session_id
        session_dir.mkdir(parents=True, exist_ok=True)

        now = datetime.now().isoformat()
        metadata = SessionMetadata(
            session_id=session_id,
            title=title or f"会话 {session_id[:15]}",
            project_path=project_path,
            created_at=now,
            updated_at=now,
            mode="BUILD",
            status="active",
            message_count=0,
            tags=[]
        )

        # 保存元数据
        self._save_metadata(session_id, metadata)

        # 创建空的摘要和 todos
        self._save_summary(session_id, SessionSummary())
        self._save_todos(session_id, [])

        # 更新索引
        self._update_index(metadata)

        return session_id

    def save_session(
        self,
        session_id: str,
        metadata: Optional[SessionMetadata] = None,
        summary: Optional[SessionSummary] = None,
        todos: Optional[List[TodoItem]] = None
    ) -> bool:
        """保存会话数据

        Args:
            session_id: 会话 ID
            metadata: 会话元数据（可选）
            summary: 上下文摘要（可选）
            todos: 任务列表（可选）

        Returns:
            是否成功
        """
        session_dir = self.sessions_dir / session_id
        if not session_dir.exists():
            session_dir.mkdir(parents=True, exist_ok=True)

        success = True

        if metadata:
            metadata.updated_at = datetime.now().isoformat()
            success = success and self._save_metadata(session_id, metadata)
            self._update_index(metadata)

        if summary:
            success = success and self._save_summary(session_id, summary)

        if todos is not None:
            success = success and self._save_todos(session_id, todos)

        return success

    def load_session(
        self,
        session_id: str
    ) -> Tuple[Optional[SessionMetadata], Optional[SessionSummary], List[TodoItem]]:
        """加载会话数据

        Args:
            session_id: 会话 ID

        Returns:
            (metadata, summary, todos) 元组
        """
        session_dir = self.sessions_dir / session_id
        if not session_dir.exists():
            return None, None, []

        metadata = self._load_metadata(session_id)
        summary = self._load_summary(session_id)
        todos = self._load_todos(session_id)

        return metadata, summary, todos

    def delete_session(self, session_id: str) -> bool:
        """删除会话

        Args:
            session_id: 会话 ID

        Returns:
            是否成功
        """
        session_dir = self.sessions_dir / session_id
        if not session_dir.exists():
            return False

        try:
            shutil.rmtree(session_dir)
            self._remove_from_index(session_id)
            return True
        except Exception:
            return False

    def session_exists(self, session_id: str) -> bool:
        """检查会话是否存在"""
        return (self.sessions_dir / session_id).exists()

    # ========================================================================
    # 会话搜索
    # ========================================================================

    def list_sessions(
        self,
        project_path: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 20
    ) -> List[SessionMetadata]:
        """列出会话

        Args:
            project_path: 按项目路径过滤（可选）
            status: 按状态过滤（可选）
            limit: 返回数量限制

        Returns:
            会话元数据列表（按更新时间倒序）
        """
        sessions = []

        # 遍历所有会话目录
        for session_dir in self.sessions_dir.iterdir():
            if not session_dir.is_dir() or session_dir.name == "index.json":
                continue

            metadata = self._load_metadata(session_dir.name)
            if not metadata:
                continue

            # 过滤条件
            if project_path and metadata.project_path != project_path:
                continue
            if status and metadata.status != status:
                continue

            sessions.append(metadata)

        # 按更新时间倒序排序
        sessions.sort(key=lambda x: x.updated_at, reverse=True)

        return sessions[:limit]

    def search_sessions(self, query: str, limit: int = 10) -> List[SessionMetadata]:
        """搜索会话

        Args:
            query: 搜索关键词（匹配标题、项目路径）
            limit: 返回数量限制

        Returns:
            匹配的会话元数据列表
        """
        query_lower = query.lower()
        sessions = []

        for session_dir in self.sessions_dir.iterdir():
            if not session_dir.is_dir():
                continue

            metadata = self._load_metadata(session_dir.name)
            if not metadata:
                continue

            # 匹配标题或项目路径
            if (query_lower in metadata.title.lower() or
                query_lower in metadata.project_path.lower() or
                query_lower in metadata.session_id.lower()):
                sessions.append(metadata)

        # 按更新时间倒序排序
        sessions.sort(key=lambda x: x.updated_at, reverse=True)

        return sessions[:limit]

    def get_recent_sessions(self, limit: int = 5) -> List[SessionMetadata]:
        """获取最近的会话

        Args:
            limit: 返回数量限制

        Returns:
            最近的会话元数据列表
        """
        return self.list_sessions(limit=limit)

    # ========================================================================
    # 内部方法 - 文件操作
    # ========================================================================

    def _save_metadata(self, session_id: str, metadata: SessionMetadata) -> bool:
        """保存元数据"""
        try:
            file_path = self.sessions_dir / session_id / "metadata.json"
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(metadata.to_dict(), f, ensure_ascii=False, indent=2)
            return True
        except Exception:
            return False

    def _load_metadata(self, session_id: str) -> Optional[SessionMetadata]:
        """加载元数据"""
        try:
            file_path = self.sessions_dir / session_id / "metadata.json"
            if file_path.exists():
                with open(file_path, 'r', encoding='utf-8') as f:
                    return SessionMetadata.from_dict(json.load(f))
        except Exception:
            pass
        return None

    def _save_summary(self, session_id: str, summary: SessionSummary) -> bool:
        """保存摘要"""
        try:
            file_path = self.sessions_dir / session_id / "summary.json"
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(summary.to_dict(), f, ensure_ascii=False, indent=2)
            return True
        except Exception:
            return False

    def _load_summary(self, session_id: str) -> Optional[SessionSummary]:
        """加载摘要"""
        try:
            file_path = self.sessions_dir / session_id / "summary.json"
            if file_path.exists():
                with open(file_path, 'r', encoding='utf-8') as f:
                    return SessionSummary.from_dict(json.load(f))
        except Exception:
            pass
        return None

    def _save_todos(self, session_id: str, todos: List[TodoItem]) -> bool:
        """保存任务列表"""
        try:
            file_path = self.sessions_dir / session_id / "todos.json"
            data = [todo.to_dict() for todo in todos]
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            return True
        except Exception:
            return False

    def _load_todos(self, session_id: str) -> List[TodoItem]:
        """加载任务列表"""
        try:
            file_path = self.sessions_dir / session_id / "todos.json"
            if file_path.exists():
                with open(file_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    return [TodoItem.from_dict(item) for item in data]
        except Exception:
            pass
        return []

    # ========================================================================
    # 消息历史
    # ========================================================================

    def save_messages(
        self,
        session_id: str,
        messages: List[Dict[str, Any]]
    ) -> bool:
        """保存消息历史

        Args:
            session_id: 会话 ID
            messages: 消息列表

        Returns:
            是否成功
        """
        try:
            session_dir = self.sessions_dir / session_id
            if not session_dir.exists():
                session_dir.mkdir(parents=True, exist_ok=True)

            file_path = session_dir / "messages.json"
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(messages, f, ensure_ascii=False, indent=2)
            return True
        except Exception:
            return False

    def load_messages(self, session_id: str) -> List[Dict[str, Any]]:
        """加载消息历史

        Args:
            session_id: 会话 ID

        Returns:
            消息列表
        """
        try:
            file_path = self.sessions_dir / session_id / "messages.json"
            if file_path.exists():
                with open(file_path, 'r', encoding='utf-8') as f:
                    return json.load(f)
        except Exception:
            pass
        return []

    def append_message(
        self,
        session_id: str,
        message: Dict[str, Any]
    ) -> bool:
        """追加单条消息到历史

        Args:
            session_id: 会话 ID
            message: 消息 {"role": "user/assistant", "content": "...", ...}

        Returns:
            是否成功
        """
        try:
            messages = self.load_messages(session_id)
            messages.append(message)
            return self.save_messages(session_id, messages)
        except Exception:
            return False

    # ========================================================================
    # 状态管理
    # ========================================================================

    def update_status(self, session_id: str, status: str) -> bool:
        """更新会话状态

        Args:
            session_id: 会话 ID
            status: 新状态 (active/paused/completed/interrupted)

        Returns:
            是否成功
        """
        metadata = self._load_metadata(session_id)
        if not metadata:
            return False

        metadata.status = status
        metadata.updated_at = datetime.now().isoformat()
        return self._save_metadata(session_id, metadata)

    def increment_message_count(self, session_id: str) -> bool:
        """增加消息计数

        Args:
            session_id: 会话 ID

        Returns:
            是否成功
        """
        metadata = self._load_metadata(session_id)
        if not metadata:
            return False

        metadata.message_count += 1
        metadata.updated_at = datetime.now().isoformat()
        return self._save_metadata(session_id, metadata)

    def update_title(self, session_id: str, title: str) -> bool:
        """更新会话标题

        Args:
            session_id: 会话 ID
            title: 新标题

        Returns:
            是否成功
        """
        metadata = self._load_metadata(session_id)
        if not metadata:
            return False

        metadata.title = title
        metadata.updated_at = datetime.now().isoformat()
        success = self._save_metadata(session_id, metadata)
        if success:
            self._update_index(metadata)
        return success


# ============================================================================
# 数据迁移工具
# ============================================================================

def migrate_todos_to_sessions(sessions_dir: Optional[Path] = None) -> int:
    """迁移旧的 todos 数据到新的 sessions 结构

    Args:
        sessions_dir: 会话存储目录

    Returns:
        迁移的会话数量
    """
    lumos_dir = Path.home() / ".lumos"
    old_todos_dir = lumos_dir / "todos"
    new_sessions_dir = sessions_dir or lumos_dir / "sessions"

    if not old_todos_dir.exists():
        return 0

    new_sessions_dir.mkdir(parents=True, exist_ok=True)
    migrated_count = 0

    for todo_file in old_todos_dir.glob("*.json"):
        session_id = todo_file.stem

        # 跳过已迁移的会话
        session_dir = new_sessions_dir / session_id
        if session_dir.exists():
            continue

        try:
            # 创建会话目录
            session_dir.mkdir(parents=True, exist_ok=True)

            # 移动 todos 文件
            shutil.copy(todo_file, session_dir / "todos.json")

            # 创建基础 metadata
            now = datetime.now().isoformat()
            metadata = SessionMetadata(
                session_id=session_id,
                title=f"迁移会话 {session_id[:15]}",
                project_path="",
                created_at=now,
                updated_at=now,
                mode="BUILD",
                status="paused",
                message_count=0,
                tags=["migrated"]
            )

            # 保存 metadata
            metadata_file = session_dir / "metadata.json"
            with open(metadata_file, 'w', encoding='utf-8') as f:
                json.dump(metadata.to_dict(), f, ensure_ascii=False, indent=2)

            # 创建空的 summary
            summary_file = session_dir / "summary.json"
            with open(summary_file, 'w', encoding='utf-8') as f:
                json.dump(SessionSummary().to_dict(), f, ensure_ascii=False, indent=2)

            migrated_count += 1

        except Exception:
            # 迁移失败，清理
            if session_dir.exists():
                shutil.rmtree(session_dir)

    return migrated_count
