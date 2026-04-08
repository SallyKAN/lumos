"""
Edge TTS 合成工具。
"""

from __future__ import annotations

import asyncio
import base64
import os
import re
import tempfile
from pathlib import Path
from typing import Dict, List, Optional

try:
    import edge_tts
except ImportError:  # pragma: no cover - 运行时依赖
    edge_tts = None


_DEFAULT_VOICE = "zh-CN-XiaoyiNeural"
_DEFAULT_RATE = "+0%"


def _normalize_rate(rate: Optional[str]) -> str:
    """规范化 Edge TTS 语速参数。

    Args:
        rate: 语速字符串或数字字符串。

    Returns:
        Edge TTS 兼容的 rate 字符串。
    """
    if not rate:
        return _DEFAULT_RATE

    rate_text = str(rate).strip()
    if not rate_text:
        return _DEFAULT_RATE

    if rate_text.endswith("%"):
        if rate_text.startswith(("+", "-")):
            return rate_text
        return f"+{rate_text}"

    if re.fullmatch(r"[+-]?\d+", rate_text):
        sign = "+" if not rate_text.startswith("-") else ""
        return f"{sign}{rate_text}%"

    return rate_text


def _normalize_tts_text(text: str) -> str:
    """清理文本，避免影响合成。

    Args:
        text: 原始文本。

    Returns:
        清理后的文本。
    """
    cleaned = text or ""
    cleaned = re.sub(r"```[\s\S]*?```", " ", cleaned)
    cleaned = re.sub(r"`[^`]+`", "", cleaned)
    cleaned = re.sub(r"[*_~`]", "", cleaned)
    cleaned = re.sub(
        r"^\s*[-*]\s+",
        "",
        cleaned,
        flags=re.MULTILINE
    )
    cleaned = re.sub(
        r"^\s*\d+[.)]\s+",
        "",
        cleaned,
        flags=re.MULTILINE
    )
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned.strip()


def _split_tts_text(text: str, max_len: int = 160) -> List[str]:
    """按标点和长度分段文本。

    Args:
        text: 已清理的文本。
        max_len: 单段最大长度。

    Returns:
        分段后的文本列表。
    """
    if not text:
        return []

    parts = re.split(r"([。！？!?；;，,])", text)
    chunks: List[str] = []
    current = ""

    for index in range(0, len(parts), 2):
        segment = parts[index].strip()
        punct = parts[index + 1] if index + 1 < len(parts) else ""
        piece = f"{segment}{punct}".strip()
        if not piece:
            continue

        if len(current) + len(piece) <= max_len:
            current += piece
            continue

        if current:
            chunks.append(current)
            current = ""

        if len(piece) <= max_len:
            current = piece
            continue

        for start in range(0, len(piece), max_len):
            chunks.append(piece[start:start + max_len])

    if current:
        chunks.append(current)

    return chunks


async def _synthesize_edge_chunks_to_bytes(
    chunks: List[str],
    voice: str,
    rate: str
) -> bytes:
    """合成分段并合并为 MP3 字节流。

    Args:
        chunks: 文本分段列表。
        voice: 语音角色。
        rate: 语速参数。

    Returns:
        合并后的 MP3 字节数据。
    """
    if not chunks:
        return b""

    if edge_tts is None:
        raise RuntimeError("edge-tts not installed")

    rate_value = _normalize_rate(rate)

    with tempfile.TemporaryDirectory() as temp_dir:
        tasks = []
        for index, chunk in enumerate(chunks):
            temp_path = os.path.join(temp_dir, f"chunk_{index}.mp3")
            communicate = edge_tts.Communicate(
                chunk,
                voice=voice,
                rate=rate_value
            )
            tasks.append(communicate.save(temp_path))

        await asyncio.gather(*tasks)

        audio_bytes = b"".join(
            Path(
                os.path.join(temp_dir, f"chunk_{index}.mp3")
            ).read_bytes()
            for index in range(len(chunks))
        )

    return audio_bytes


async def synthesize_audio_base64_async(
    text: str,
    voice: Optional[str] = None,
    rate: Optional[str] = None
) -> Dict[str, object]:
    """合成语音并返回 Base64 音频。

    Args:
        text: 需要合成的文本。
        voice: 可选语音角色。
        rate: 可选语速参数。

    Returns:
        包含音频 Base64 和 MIME 的字典。
    """
    cleaned = _normalize_tts_text(text)
    if not cleaned:
        return {"success": False, "error": "empty_text"}

    voice_name = voice or os.getenv("TTS_VOICE", _DEFAULT_VOICE)
    rate_value = rate or os.getenv("TTS_RATE", _DEFAULT_RATE)

    chunks = _split_tts_text(cleaned)
    audio_bytes = await _synthesize_edge_chunks_to_bytes(
        chunks,
        voice_name,
        rate_value
    )

    if not audio_bytes:
        return {"success": False, "error": "synthesis_failed"}

    audio_b64 = base64.b64encode(audio_bytes).decode("ascii")
    return {
        "success": True,
        "audio_base64": audio_b64,
        "audio_mime": "audio/mpeg"
    }
