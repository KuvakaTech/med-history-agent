"""Deepgram STT — async, uses Deepgram REST API via httpx."""
from __future__ import annotations

import logging
from typing import Optional

import httpx

from app.core.config import settings

log = logging.getLogger(__name__)


def _deepgram_language(patient_language: Optional[str]) -> Optional[str]:
    """Map the session's patient language to a Deepgram language parameter.

    nova-3 defaults to English; Hindi (and Hindi/English code-switching, common
    with Indian patients) needs the multilingual mode. English needs no param.
    """
    if not patient_language:
        return None
    lang = patient_language.strip().lower()
    if lang in ("en", "english"):
        return None
    return "multi"


async def transcribe_bytes(
    audio_data: bytes,
    mimetype: str = "audio/webm;codecs=opus",
    language: Optional[str] = None,
) -> str:
    """Transcribe audio bytes using Deepgram STT REST API. Returns plain text."""
    url = (
        f"https://api.deepgram.com/v1/listen"
        f"?model={settings.DEEPGRAM_STT_MODEL}&smart_format=true&punctuate=true"
    )
    dg_lang = _deepgram_language(language)
    if dg_lang:
        url += f"&language={dg_lang}"
    try:
        async with httpx.AsyncClient(timeout=60) as client:
            response = await client.post(
                url,
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
