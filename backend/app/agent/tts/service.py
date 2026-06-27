"""Deepgram TTS — returns MP3 bytes using the v7 async SDK."""
from __future__ import annotations

import logging

from app.core.config import settings

log = logging.getLogger(__name__)


async def synthesize(text: str) -> bytes:
    """Synthesize text to MP3 bytes using Deepgram TTS (SDK v7)."""
    from deepgram import AsyncDeepgramClient

    dg = AsyncDeepgramClient(api_key=settings.DEEPGRAM_API_KEY)

    chunks: list[bytes] = []
    async for chunk in dg.speak.v1.audio.generate(
        text=text,
        model=settings.DEEPGRAM_TTS_MODEL,
    ):
        chunks.append(chunk)

    return b"".join(chunks)
