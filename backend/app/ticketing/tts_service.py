"""TTS for the ticketing flow.

Uses stock ElevenLabs multilingual voice (NOT a cloned voice).
Falls back to Deepgram TTS if ElevenLabs is unavailable.

This is intentionally separate from app/agent/tts/service.py which may use
a cloned voice ID for the clinical flow.
"""
from __future__ import annotations

import logging

import httpx

from app.core.config import settings

log = logging.getLogger(__name__)

# Stock ElevenLabs multilingual voice for ticketing (no clone)
_MULTILINGUAL_VOICE_ID = "pNInz6obpgDQGcFmaJgB"  # Adam — multilingual v2 stock voice
_MULTILINGUAL_MODEL = "eleven_multilingual_v2"

# Hindi-friendly Deepgram fallback
_DG_TTS_MODEL_HI = "aura-luna-en"  # Deepgram doesn't have Hindi; browser fallback is handled FE-side


async def synthesize_ticket(text: str, language: str = "hi") -> bytes:
    """Synthesize text to MP3 bytes for the ticketing flow.

    Uses ElevenLabs multilingual stock voice (not cloned).
    Falls back to Deepgram on failure.
    """
    if settings.ELEVENLABS_API_KEY:
        try:
            return await _elevenlabs_multilingual(text)
        except Exception as exc:
            log.warning("ElevenLabs ticket TTS failed (%s), falling back to Deepgram", exc)
    return await _deepgram_tts(text)


async def _elevenlabs_multilingual(text: str) -> bytes:
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.post(
            f"https://api.elevenlabs.io/v1/text-to-speech/{_MULTILINGUAL_VOICE_ID}",
            headers={
                "xi-api-key": settings.ELEVENLABS_API_KEY,
                "Content-Type": "application/json",
                "Accept": "audio/mpeg",
            },
            json={
                "text": text,
                "model_id": _MULTILINGUAL_MODEL,
                "voice_settings": {
                    "stability": 0.5,
                    "similarity_boost": 0.75,
                    "speed": 1.0,  # keep conversational pace
                },
            },
        )
        response.raise_for_status()
        return response.content


async def _deepgram_tts(text: str) -> bytes:
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
