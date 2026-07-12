"""TTS — ElevenLabs cloned voice (primary, English + Hindi), Deepgram fallback."""
from __future__ import annotations

import logging

import httpx

from app.core.config import settings

log = logging.getLogger(__name__)


async def synthesize(text: str) -> bytes:
    """Synthesize text to MP3 bytes. ElevenLabs cloned voice if configured, else Deepgram."""
    if settings.ELEVENLABS_API_KEY and settings.ELEVENLABS_VOICE_ID:
        try:
            return await _elevenlabs_synthesize(text)
        except Exception as exc:
            log.warning("ElevenLabs TTS failed (%s), falling back to Deepgram", exc)
    return await _deepgram_synthesize(text)


async def _elevenlabs_synthesize(text: str) -> bytes:
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.post(
            f"https://api.elevenlabs.io/v1/text-to-speech/{settings.ELEVENLABS_VOICE_ID}",
            headers={
                "xi-api-key": settings.ELEVENLABS_API_KEY,
                "Content-Type": "application/json",
                "Accept": "audio/mpeg",
            },
            json={
                "text": text,
                "model_id": settings.ELEVENLABS_MODEL,
            },
        )
        response.raise_for_status()
        return response.content


async def _deepgram_synthesize(text: str) -> bytes:
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
