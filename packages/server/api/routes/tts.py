"""
TTS REST API 路由。
"""

from typing import Dict, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from packages.server.edge_tts import synthesize_audio_base64_async


router = APIRouter(prefix="/edge_tts", tags=["tts"])


class TtsRequest(BaseModel):
    """TTS 请求。"""
    text: str
    voice: Optional[str] = None
    rate: Optional[str] = None


@router.post("")
async def synthesize_audio(request: TtsRequest) -> Dict[str, object]:
    """生成 TTS 音频（Base64）。"""
    text = request.text.strip()
    if not text:
        raise HTTPException(status_code=400, detail="Empty text")

    try:
        result = await synthesize_audio_base64_async(
            text=text,
            voice=request.voice,
            rate=request.rate
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    if not result.get("success"):
        raise HTTPException(status_code=400, detail="TTS synthesis failed")

    return result
