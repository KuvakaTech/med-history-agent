"""Deepgram real-time streaming STT client for the ticketing voice flow.

Connects to Deepgram's WebSocket streaming API using nova-3 with server-side
endpointing (UtteranceEnd events). Audio is sent continuously; the caller
receives interim transcripts and final utterances when Deepgram's endpointing
fires.

The caller drives the lifecycle:
    stream = DeepgramLiveStream(language="hi")
    await stream.connect()
    await stream.send_audio(pcm_bytes)        # call repeatedly
    async for event in stream.events():       # type: "partial" | "utterance_end" | "error"
        ...
    await stream.close()
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from enum import Enum
from typing import AsyncGenerator, Optional
from urllib.parse import urlencode

import websockets
from websockets.exceptions import ConnectionClosed

from app.core.config import settings

log = logging.getLogger(__name__)

# Deepgram endpointing — fire UtteranceEnd after this many ms of silence
_UTTERANCE_END_MS = 1000


class DGEventType(str, Enum):
    PARTIAL = "partial"          # interim transcript
    UTTERANCE_END = "utterance_end"  # endpointing fired — patient finished speaking
    ERROR = "error"


@dataclass
class DGEvent:
    type: DGEventType
    text: str = ""
    is_final: bool = False


class DeepgramLiveStream:
    def __init__(self, language: str = "hi") -> None:
        self._language = language
        self._ws: Optional[websockets.WebSocketClientProtocol] = None  # type: ignore[type-arg]

    def _connect_url(self) -> str:
        lang_param = "multi" if self._language not in ("en", "english") else "en-US"
        params = [
            ("model", settings.DEEPGRAM_STT_MODEL),
            ("encoding", "linear16"),
            ("sample_rate", "16000"),
            ("channels", "1"),
            ("smart_format", "true"),
            ("punctuate", "true"),
            ("interim_results", "true"),
            ("utterance_end_ms", str(_UTTERANCE_END_MS)),
            ("language", lang_param),
        ]
        return f"wss://api.deepgram.com/v1/listen?{urlencode(params)}"

    async def connect(self) -> None:
        self._ws = await websockets.connect(
            self._connect_url(),
            additional_headers={"Authorization": f"Token {settings.DEEPGRAM_API_KEY}"},
            ping_interval=20,
            ping_timeout=20,
        )

    async def close(self) -> None:
        if self._ws is not None:
            try:
                await self._ws.close()
            except Exception:
                pass
            self._ws = None

    async def send_audio(self, pcm_bytes: bytes) -> None:
        if self._ws is None:
            return
        try:
            await self._ws.send(pcm_bytes)
        except Exception as exc:
            log.warning("DG send_audio failed: %s", exc)

    async def keepalive(self) -> None:
        """Send a keepalive JSON frame to prevent idle timeout."""
        if self._ws is None:
            return
        try:
            await self._ws.send(json.dumps({"type": "KeepAlive"}))
        except Exception:
            pass

    async def finalize(self) -> None:
        """Tell Deepgram the audio stream is done — flush any buffered transcript."""
        if self._ws is None:
            return
        try:
            await self._ws.send(json.dumps({"type": "Finalize"}))
        except Exception:
            pass

    async def events(self) -> AsyncGenerator[DGEvent, None]:
        if self._ws is None:
            return
        try:
            async for raw in self._ws:
                if isinstance(raw, bytes):
                    continue
                try:
                    payload = json.loads(raw)
                except Exception:
                    continue

                msg_type = payload.get("type", "")

                if msg_type == "Results":
                    channel = (payload.get("channel") or {})
                    alternatives = channel.get("alternatives") or []
                    text = alternatives[0].get("transcript", "") if alternatives else ""
                    is_final = payload.get("is_final", False)
                    speech_final = payload.get("speech_final", False)
                    if text:
                        yield DGEvent(
                            type=DGEventType.PARTIAL,
                            text=text,
                            is_final=is_final or speech_final,
                        )

                elif msg_type == "UtteranceEnd":
                    yield DGEvent(type=DGEventType.UTTERANCE_END)

                elif msg_type in ("Error", "error"):
                    error_msg = payload.get("message", "Unknown Deepgram error")
                    log.error("Deepgram error: %s", error_msg)
                    yield DGEvent(type=DGEventType.ERROR, text=error_msg)
                    return

        except ConnectionClosed:
            yield DGEvent(type=DGEventType.ERROR, text="Deepgram connection closed")
        except Exception as exc:
            log.error("DeepgramLiveStream error: %s", exc)
            yield DGEvent(type=DGEventType.ERROR, text=str(exc))
