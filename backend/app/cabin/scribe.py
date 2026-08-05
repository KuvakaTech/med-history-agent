"""Outbound ElevenLabs Scribe v2 Realtime client.

Knows nothing clinical — just connects, streams PCM16 audio in, and yields
parsed transcription events out. Error classification and reconnect policy
live here so callers only see "keep going" / "reconnecting" / "fatal".
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
from dataclasses import dataclass
from enum import Enum
from typing import Any, AsyncGenerator, Optional
from urllib.parse import urlencode

import websockets
from websockets.exceptions import ConnectionClosed

from app.core.config import settings

log = logging.getLogger(__name__)

RECONNECT_BACKOFFS = (0.5, 1.0, 2.0)
MAX_RECONNECT_ATTEMPTS = 3

# Word-level timing for utterance start/end. Note ElevenLabs currently rejects this
# combined with filter_background_audio — the two cannot both be on.
INCLUDE_TIMESTAMPS = True

# ElevenLabs error events, classified per app/cabin — see plan §7 (Failure handling).
_FATAL_NO_RETRY = {"auth_error", "quota_exceeded"}
_RETRYABLE = {"transcriber_error", "session_time_limit_exceeded"}
_TRANSIENT = {"rate_limited", "commit_throttled", "queue_overflow"}
_OUR_BUG = {"chunk_size_exceeded", "input_error", "invalid_request"}
_INFORMATIONAL = {"insufficient_audio_activity"}


class ScribeErrorClass(str, Enum):
    FATAL = "fatal"
    RETRYABLE = "retryable"
    TRANSIENT = "transient"
    OUR_BUG = "our_bug"
    INFORMATIONAL = "informational"
    UNKNOWN = "unknown"


@dataclass
class ScribeEvent:
    type: str
    data: dict[str, Any]
    error_class: Optional[ScribeErrorClass] = None


def classify_error(event_type: str) -> ScribeErrorClass:
    if event_type in _FATAL_NO_RETRY:
        return ScribeErrorClass.FATAL
    if event_type in _RETRYABLE:
        return ScribeErrorClass.RETRYABLE
    if event_type in _TRANSIENT:
        return ScribeErrorClass.TRANSIENT
    if event_type in _OUR_BUG:
        return ScribeErrorClass.OUR_BUG
    if event_type in _INFORMATIONAL:
        return ScribeErrorClass.INFORMATIONAL
    return ScribeErrorClass.UNKNOWN


class ScribeStream:
    """One live connection to ElevenLabs Scribe v2 Realtime.

    Usage:
        stream = ScribeStream(secondary_languages=[...], keyterms=[...])
        await stream.connect()
        await stream.send_audio(pcm_bytes)
        async for event in stream.events():
            ...
        await stream.close()
    """

    def __init__(
        self,
        secondary_languages: Optional[list[str]] = None,
        keyterms: Optional[list[str]] = None,
        language_code: Optional[str] = None,
    ) -> None:
        self._secondary_languages = secondary_languages or []
        self._keyterms = (keyterms or [])[:50]
        self._language_code = language_code
        self._ws: Optional[Any] = None
        self._reconnect_attempts = 0
        # Set while a planned cutover is in flight so events() can tell a deliberate
        # socket swap from a real drop — see rolling_reconnect().
        self._rolling_over = False

    def _connect_url(self) -> str:
        params: list[tuple[str, Any]] = [
            ("model_id", settings.ELEVENLABS_STT_MODEL),
            ("audio_format", "pcm_16000"),
            ("commit_strategy", "vad"),
            ("vad_silence_threshold_secs", settings.CABIN_STT_VAD_SILENCE_SECS),
            ("filter_background_audio", str(
                settings.CABIN_STT_FILTER_BACKGROUND_AUDIO
            ).lower()),
            ("no_verbatim", str(settings.CABIN_STT_NO_VERBATIM).lower()),
            ("include_timestamps", str(INCLUDE_TIMESTAMPS).lower()),
            ("include_language_detection", "true"),
        ]
        if self._language_code:
            params.append(("language_code", self._language_code))
        # ElevenLabs expects one query param per code (ISO 639-3), not a comma-joined list.
        for code in self._secondary_languages:
            params.append(("secondary_languages", code))
        if self._keyterms:
            params.append(("keyterms", ",".join(self._keyterms)))
        return f"{settings.ELEVENLABS_STT_WS_URL}?{urlencode(params)}"

    async def _open(self) -> Any:
        return await websockets.connect(
            self._connect_url(),
            additional_headers={"xi-api-key": settings.ELEVENLABS_API_KEY},
            ping_interval=20,
            ping_timeout=20,
        )

    async def connect(self) -> None:
        self._ws = await self._open()

    async def close(self) -> None:
        if self._ws is not None:
            try:
                await self._ws.close()
            except Exception:
                pass
            self._ws = None

    async def send_audio(self, pcm_bytes: bytes) -> None:
        if self._ws is None:
            raise RuntimeError("ScribeStream not connected")
        await self._ws.send(
            json.dumps(
                {
                    "message_type": "input_audio_chunk",
                    "audio_base_64": base64.b64encode(pcm_bytes).decode("ascii"),
                }
            )
        )

    async def _reconnect(self) -> bool:
        """Attempt to reconnect after a retryable failure. Returns True on success."""
        for backoff in RECONNECT_BACKOFFS:
            self._reconnect_attempts += 1
            await asyncio.sleep(backoff)
            try:
                await self.connect()
                self._reconnect_attempts = 0
                return True
            except Exception as exc:
                log.warning(
                    "Scribe reconnect attempt %d failed: %s",
                    self._reconnect_attempts,
                    exc,
                )
        return False

    async def rolling_reconnect(self) -> bool:
        """Planned cutover to a fresh socket, called on a timer — ElevenLabs does not
        document a session time limit, so we replace the connection before any
        undocumented cap can hit us.

        Opens the replacement first and only swaps once it is live, so a failed cutover
        leaves the working socket untouched. `_rolling_over` is set before the old
        socket is closed: closing it wakes the pending recv() inside events(), and
        without the flag that path would read a deliberate swap as an unexpected drop
        and reconnect again — discarding the socket we just opened.
        """
        old_ws = self._ws
        try:
            new_ws = await self._open()
        except Exception as exc:
            log.warning("Rolling reconnect failed, keeping existing socket: %s", exc)
            return False

        self._rolling_over = True
        self._ws = new_ws
        if old_ws is not None:
            try:
                await old_ws.close()
            except Exception:
                pass
        return True

    async def events(self) -> AsyncGenerator[ScribeEvent, None]:
        """Yields parsed events. On a retryable failure, reconnects transparently
        (up to MAX_RECONNECT_ATTEMPTS) and keeps yielding from the caller's view.
        Fatal errors and exhausted retries end the generator."""
        while True:
            if self._ws is None:
                return
            try:
                raw = await self._ws.recv()
            except ConnectionClosed:
                if self._rolling_over:
                    # Planned cutover: self._ws already points at the live replacement,
                    # so pick it up on the next iteration without a reconnect round.
                    self._rolling_over = False
                    continue
                yield ScribeEvent(
                    type="reconnecting", data={}, error_class=ScribeErrorClass.RETRYABLE
                )
                if (
                    self._reconnect_attempts >= MAX_RECONNECT_ATTEMPTS
                    or not await self._reconnect()
                ):
                    yield ScribeEvent(
                        type="fatal_disconnect",
                        data={},
                        error_class=ScribeErrorClass.FATAL,
                    )
                    return
                continue

            try:
                payload = json.loads(raw)
            except (TypeError, ValueError):
                continue

            # ElevenLabs discriminates on "message_type", not "type".
            event_type = payload.get("message_type", "unknown")

            # With timestamps on, every commit arrives twice — once plain and once
            # with word timings. Drop the plain one so callers record one utterance.
            if INCLUDE_TIMESTAMPS and event_type == "committed_transcript":
                continue
            if (
                event_type
                in _FATAL_NO_RETRY | _RETRYABLE | _TRANSIENT | _OUR_BUG | _INFORMATIONAL
            ):
                error_class = classify_error(event_type)
                yield ScribeEvent(
                    type=event_type, data=payload, error_class=error_class
                )
                if error_class == ScribeErrorClass.FATAL:
                    return
                if error_class == ScribeErrorClass.RETRYABLE:
                    if (
                        self._reconnect_attempts >= MAX_RECONNECT_ATTEMPTS
                        or not await self._reconnect()
                    ):
                        yield ScribeEvent(
                            type="fatal_disconnect",
                            data={},
                            error_class=ScribeErrorClass.FATAL,
                        )
                        return
                continue

            yield ScribeEvent(type=event_type, data=payload)
