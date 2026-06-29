"""Deepgram STT — async, uses Deepgram REST API via httpx."""
from __future__ import annotations

import logging

import httpx

from app.core.config import settings

log = logging.getLogger(__name__)


async def transcribe_bytes(audio_data: bytes, mimetype: str = "audio/webm;codecs=opus") -> str:
    """Transcribe audio bytes using Deepgram STT REST API. Returns plain text."""
    try:
        async with httpx.AsyncClient(timeout=60) as client:
            response = await client.post(
                f"https://api.deepgram.com/v1/listen?model={settings.DEEPGRAM_STT_MODEL}&smart_format=true&punctuate=true",
                headers={
                    "Authorization": f"Token {settings.DEEPGRAM_API_KEY}",
                    "Content-Type": mimetype,
                },
                content=audio_data,
            )
            response.raise_for_status()
            data = response.json()
            return data["results"]["channels"][0]["alternatives"][0]["transcript"]
    except Exception as exc:
        log.error("Deepgram STT error: %s", exc)
        raise RuntimeError(f"Transcription failed: {exc}") from exc
