"""
媒体标记解析器

解析消息中的 MEDIA: 标记并处理媒体文件。
"""

import base64
import mimetypes
import os
import re
import logging
from typing import List, Optional, Tuple

from .media_types import MediaItem, MediaType, get_media_type_from_mime
from .media_manager import MediaManager

logger = logging.getLogger(__name__)

# MEDIA 标记正则表达式：匹配独占一行的 MEDIA:<path>
MEDIA_PATTERN = re.compile(r'^MEDIA:(.+)$', re.MULTILINE)


class MediaParser:
    """媒体标记解析器

    解析消息内容中的 MEDIA: 标记，处理对应的媒体文件。
    """

    def __init__(
        self,
        api_base_url: str = "",
        base64_threshold: int = MediaManager.DEFAULT_BASE64_THRESHOLD
    ):
        """初始化解析器。

        Args:
            api_base_url: API 基础 URL（用于生成媒体访问 URL）
            base64_threshold: Base64 编码阈值（字节）
        """
        self.api_base_url = api_base_url.rstrip('/')
        self.base64_threshold = base64_threshold
        self.media_manager = MediaManager()

    def parse(self, content: str) -> Tuple[str, List[MediaItem]]:
        """解析内容中的 MEDIA 标记。

        Args:
            content: 包含 MEDIA 标记的内容

        Returns:
            (clean_content, media_items) 元组
            - clean_content: 移除 MEDIA 标记后的内容
            - media_items: 解析出的媒体项列表
        """
        if not content:
            return "", []

        media_items: List[MediaItem] = []
        processed_paths = set()

        # 查找所有 MEDIA 标记
        for match in MEDIA_PATTERN.finditer(content):
            path = match.group(1).strip()

            # 避免重复处理
            if path in processed_paths:
                continue
            processed_paths.add(path)

            # 处理媒体文件
            item = self._process_media_file(path)
            if item:
                media_items.append(item)

        # 移除 MEDIA 标记行
        clean_content = MEDIA_PATTERN.sub('', content)
        # 清理多余的空行
        clean_content = re.sub(r'\n{3,}', '\n\n', clean_content)
        clean_content = clean_content.strip()

        return clean_content, media_items

    def _process_media_file(self, path: str) -> Optional[MediaItem]:
        """处理单个媒体文件。

        Args:
            path: 文件路径

        Returns:
            MediaItem 或 None（如果文件不存在或处理失败）
        """
        # 检查文件是否存在
        if not os.path.exists(path):
            logger.warning(f"Media file not found: {path}")
            return None

        try:
            file_size = os.path.getsize(path)
            filename = os.path.basename(path)

            # 获取 MIME 类型
            mime_type, _ = mimetypes.guess_type(path)
            if not mime_type:
                mime_type = "application/octet-stream"

            # 获取媒体类型
            media_type = get_media_type_from_mime(mime_type)

            # 创建 MediaItem
            item = MediaItem(
                type=media_type.value,
                mime_type=mime_type,
                filename=filename,
                file_path=path,
                file_size=file_size
            )

            # 根据文件大小决定使用 Base64 还是 URL
            if file_size <= self.base64_threshold:
                item.base64_data = self._encode_base64(path)
            else:
                item.url = self._generate_url(path)

            return item

        except Exception as e:
            logger.error(f"Failed to process media file {path}: {e}")
            return None

    def _encode_base64(self, path: str) -> str:
        """将文件编码为 Base64。

        Args:
            path: 文件路径

        Returns:
            Base64 编码字符串
        """
        with open(path, 'rb') as f:
            return base64.b64encode(f.read()).decode('ascii')

    def _generate_url(self, path: str) -> str:
        """生成媒体文件的访问 URL。

        Args:
            path: 文件路径

        Returns:
            访问 URL
        """
        # 获取相对路径
        relative_path = self.media_manager.get_relative_path(path)

        if relative_path:
            # 文件在媒体目录内，使用 /api/media/ 路径
            return f"{self.api_base_url}/api/media/{relative_path}"
        else:
            # 文件在媒体目录外，使用完整路径（需要特殊处理）
            # 这里返回一个标记，让前端知道需要通过其他方式获取
            logger.warning(
                f"Media file outside base dir: {path}"
            )
            return f"{self.api_base_url}/api/media/external?path={path}"


def parse_media_content(
    content: str,
    api_base_url: str = ""
) -> Tuple[str, List[dict]]:
    """便捷函数：解析内容中的 MEDIA 标记。

    Args:
        content: 包含 MEDIA 标记的内容
        api_base_url: API 基础 URL

    Returns:
        (clean_content, media_items) 元组
    """
    parser = MediaParser(api_base_url=api_base_url)
    clean_content, items = parser.parse(content)
    return clean_content, [item.to_dict() for item in items]
