"""
媒体文件管理器

负责媒体文件的保存、读取和清理。
"""

import os
import time
import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


class MediaManager:
    """媒体文件管理器

    提供媒体文件的存储、访问和清理功能。
    """

    # 默认配置
    DEFAULT_BASE_DIR = "~/.lumos/media"
    DEFAULT_BASE64_THRESHOLD = 100 * 1024  # 100KB
    DEFAULT_MAX_FILE_SIZE = 50 * 1024 * 1024  # 50MB
    DEFAULT_CLEANUP_DAYS = 7

    def __init__(
        self,
        base_dir: Optional[str] = None,
        base64_threshold: Optional[int] = None,
        max_file_size: Optional[int] = None
    ):
        """初始化媒体管理器。

        Args:
            base_dir: 媒体文件基础目录
            base64_threshold: Base64 编码阈值（字节）
            max_file_size: 最大文件大小（字节）
        """
        self.base_dir = os.path.expanduser(
            base_dir or os.getenv("MEDIA_OUTPUT_DIR", self.DEFAULT_BASE_DIR)
        )
        self.base64_threshold = base64_threshold or int(
            os.getenv(
                "MEDIA_BASE64_THRESHOLD",
                str(self.DEFAULT_BASE64_THRESHOLD)
            )
        )
        self.max_file_size = max_file_size or int(
            os.getenv("MEDIA_MAX_FILE_SIZE", str(self.DEFAULT_MAX_FILE_SIZE))
        )

        # 确保基础目录存在
        os.makedirs(self.base_dir, exist_ok=True)

    @classmethod
    def get_output_dir(cls, session_id: str) -> str:
        """获取会话的媒体输出目录。

        Args:
            session_id: 会话 ID

        Returns:
            媒体输出目录的绝对路径
        """
        base_dir = os.path.expanduser(
            os.getenv("MEDIA_OUTPUT_DIR", cls.DEFAULT_BASE_DIR)
        )
        media_dir = os.path.join(base_dir, session_id)
        os.makedirs(media_dir, exist_ok=True)
        return media_dir

    @classmethod
    def save_media(
        cls,
        session_id: str,
        content: bytes,
        filename: str
    ) -> str:
        """保存媒体文件。

        Args:
            session_id: 会话 ID
            content: 文件内容（字节）
            filename: 文件名

        Returns:
            保存后的文件路径
        """
        media_dir = cls.get_output_dir(session_id)
        file_path = os.path.join(media_dir, filename)

        # 如果文件已存在，添加时间戳
        if os.path.exists(file_path):
            name, ext = os.path.splitext(filename)
            timestamp = int(time.time())
            filename = f"{name}_{timestamp}{ext}"
            file_path = os.path.join(media_dir, filename)

        with open(file_path, 'wb') as f:
            f.write(content)

        logger.info(f"Media file saved: {file_path}")
        return file_path

    @classmethod
    def format_media_marker(cls, path: str) -> str:
        """生成 MEDIA 标记。

        Args:
            path: 文件路径

        Returns:
            MEDIA 标记字符串
        """
        return f"MEDIA:{path}"

    def get_session_dir(self, session_id: str) -> str:
        """获取会话的媒体目录。

        Args:
            session_id: 会话 ID

        Returns:
            会话媒体目录路径
        """
        session_dir = os.path.join(self.base_dir, session_id)
        os.makedirs(session_dir, exist_ok=True)
        return session_dir

    def should_use_base64(self, file_size: int) -> bool:
        """判断是否应该使用 Base64 编码。

        Args:
            file_size: 文件大小（字节）

        Returns:
            是否使用 Base64
        """
        return file_size <= self.base64_threshold

    def cleanup_old_files(self, days: Optional[int] = None) -> int:
        """清理过期的媒体文件。

        Args:
            days: 保留天数，默认为 DEFAULT_CLEANUP_DAYS

        Returns:
            删除的文件数量
        """
        if days is None:
            days = int(
                os.getenv("MEDIA_CLEANUP_DAYS", str(self.DEFAULT_CLEANUP_DAYS))
            )

        cutoff_time = time.time() - (days * 24 * 60 * 60)
        deleted_count = 0

        for root, dirs, files in os.walk(self.base_dir):
            for filename in files:
                file_path = os.path.join(root, filename)
                try:
                    if os.path.getmtime(file_path) < cutoff_time:
                        os.remove(file_path)
                        deleted_count += 1
                        logger.info(f"Deleted old media file: {file_path}")
                except OSError as e:
                    logger.warning(f"Failed to delete {file_path}: {e}")

            # 删除空目录
            for dirname in dirs:
                dir_path = os.path.join(root, dirname)
                try:
                    if not os.listdir(dir_path):
                        os.rmdir(dir_path)
                        logger.info(f"Deleted empty directory: {dir_path}")
                except OSError:
                    pass

        return deleted_count

    def get_relative_path(self, absolute_path: str) -> Optional[str]:
        """获取相对于基础目录的路径。

        Args:
            absolute_path: 绝对路径

        Returns:
            相对路径，如果不在基础目录下则返回 None
        """
        try:
            abs_path = Path(absolute_path).resolve()
            base_path = Path(self.base_dir).resolve()
            return str(abs_path.relative_to(base_path))
        except ValueError:
            return None
