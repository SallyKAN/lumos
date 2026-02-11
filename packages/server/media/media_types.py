"""
媒体类型定义
"""

from dataclasses import dataclass
from enum import Enum
from typing import Optional


class MediaType(str, Enum):
    """媒体类型枚举"""
    IMAGE = "image"
    AUDIO = "audio"
    VIDEO = "video"
    DOCUMENT = "document"


# MIME 类型到媒体类型的映射
MIME_TO_MEDIA_TYPE = {
    # 图片
    "image/png": MediaType.IMAGE,
    "image/jpeg": MediaType.IMAGE,
    "image/jpg": MediaType.IMAGE,
    "image/gif": MediaType.IMAGE,
    "image/webp": MediaType.IMAGE,
    "image/svg+xml": MediaType.IMAGE,
    "image/bmp": MediaType.IMAGE,
    "image/ico": MediaType.IMAGE,
    "image/x-icon": MediaType.IMAGE,
    # 音频
    "audio/mpeg": MediaType.AUDIO,
    "audio/mp3": MediaType.AUDIO,
    "audio/wav": MediaType.AUDIO,
    "audio/ogg": MediaType.AUDIO,
    "audio/webm": MediaType.AUDIO,
    "audio/flac": MediaType.AUDIO,
    "audio/aac": MediaType.AUDIO,
    # 视频
    "video/mp4": MediaType.VIDEO,
    "video/webm": MediaType.VIDEO,
    "video/ogg": MediaType.VIDEO,
    "video/avi": MediaType.VIDEO,
    "video/quicktime": MediaType.VIDEO,
    "video/x-msvideo": MediaType.VIDEO,
    # 文档
    "application/pdf": MediaType.DOCUMENT,
    "application/msword": MediaType.DOCUMENT,
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document":
        MediaType.DOCUMENT,
    "application/vnd.ms-excel": MediaType.DOCUMENT,
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet":
        MediaType.DOCUMENT,
    "application/vnd.ms-powerpoint": MediaType.DOCUMENT,
    "application/vnd.openxmlformats-officedocument.presentationml.presentation":
        MediaType.DOCUMENT,
    "text/plain": MediaType.DOCUMENT,
    "text/csv": MediaType.DOCUMENT,
    "application/json": MediaType.DOCUMENT,
    "application/xml": MediaType.DOCUMENT,
}


def get_media_type_from_mime(mime_type: Optional[str]) -> MediaType:
    """根据 MIME 类型获取媒体类型。

    Args:
        mime_type: MIME 类型字符串

    Returns:
        对应的 MediaType，默认为 DOCUMENT
    """
    if not mime_type:
        return MediaType.DOCUMENT
    return MIME_TO_MEDIA_TYPE.get(mime_type.lower(), MediaType.DOCUMENT)


@dataclass
class MediaItem:
    """媒体项数据结构

    Attributes:
        type: 媒体类型 (image/audio/video/document)
        mime_type: MIME 类型
        filename: 文件名
        base64_data: Base64 编码数据（小文件）
        url: 访问 URL（大文件）
        file_path: 原始文件路径
        file_size: 文件大小（字节）
    """
    type: str
    mime_type: str
    filename: str
    base64_data: Optional[str] = None
    url: Optional[str] = None
    file_path: Optional[str] = None
    file_size: Optional[int] = None

    def to_dict(self) -> dict:
        """转换为字典格式。

        Returns:
            字典表示
        """
        result = {
            "type": self.type,
            "mimeType": self.mime_type,
            "filename": self.filename,
        }
        if self.base64_data:
            result["base64Data"] = self.base64_data
        if self.url:
            result["url"] = self.url
        return result
