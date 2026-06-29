"""Deepgram TTS — returns MP3 bytes via Deepgram REST API."""
from __future__ import annotations

import logging

import httpx

from app.core.config import settings

log = logging.getLogger(__name__)


async def synthesize(text: str) -> bytes:
    """Synthesize text to MP3 bytes using Deepgram TTS REST API."""
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.post(
            f"https://api.deepgram.com/v1/speak?model={settings.DEEPGRAM_TTS_MODEL}",
            headers={
                "Authorization": f"Token {settings.DEEPGRAM_API_KEY}",
                "Content-Type": "application/json",
            },
            json={"text": text},
        )
        response.raise_for_status()
        return response.content
