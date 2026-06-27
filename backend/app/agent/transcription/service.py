"""Deepgram STT — async, uses SDK v7 native async API."""
from __future__ import annotations

import logging

from app.core.config import settings

log = logging.getLogger(__name__)


async def transcribe_bytes(audio_data: bytes, mimetype: str = "audio/webm;codecs=opus") -> str:
    """Transcribe audio bytes using Deepgram. Returns plain text."""
    from deepgram import AsyncDeepgramClient

    dg = AsyncDeepgramClient(api_key=settings.DEEPGRAM_API_KEY)

    try:
        response = await dg.listen.v1.media.transcribe_file(
            request=audio_data,
            model=settings.DEEPGRAM_STT_MODEL,
            smart_format=True,
            punctuate=True,
        )
        return response.results.channels[0].alternatives[0].transcript
    except Exception as exc:
        log.error("Deepgram STT error: %s", exc)
        raise RuntimeError(f"Transcription failed: {exc}") from exc
