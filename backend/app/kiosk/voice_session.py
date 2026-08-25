"""Kiosk voice session — single-phase Gemini Live for Jan Sunwai."""
from __future__ import annotations

import array
import asyncio
import base64
import json
import logging
import math
import time
from datetime import datetime
from typing import Any, Optional

from fastapi import WebSocket, WebSocketDisconnect

from app.core.config import settings
from app.kiosk import events as ev
from app.kiosk.gemini_live import GeminiLiveSession, LiveEvent, complaint_tools
from app.kiosk.hindi_display import to_devanagari_display
from app.kiosk.models import KioskSession, KioskTranscriptEntry
from app.kiosk.post_call_extract import run_post_call_extract
from app.kiosk.prompts import kickoff_text, system_instruction
from app.kiosk.session_store import kiosk_session_store

log = logging.getLogger(__name__)

_MAX_AUDIO_FRAME_BYTES = 64 * 1024
_SEND_TIMEOUT = 8.0
_DUCK_RMS_THRESHOLD = 600.0

_live_counts: dict[str, int] = {}
_live_lock = asyncio.Lock()


def reset_live_slots() -> None:
    _live_counts.clear()


async def acquire_live_slot(centre_id: str) -> bool:
    cap = settings.KIOSK_MAX_CONCURRENT_LIVE_SESSIONS_PER_CENTRE
    async with _live_lock:
        n = _live_counts.get(centre_id, 0)
        if n >= cap:
            return False
        _live_counts[centre_id] = n + 1
        return True


async def release_live_slot(centre_id: str) -> None:
    async with _live_lock:
        n = _live_counts.get(centre_id, 0)
        if n <= 1:
            _live_counts.pop(centre_id, None)
        else:
            _live_counts[centre_id] = n - 1


def pcm16_rms(frame: bytes) -> float:
    n = len(frame) // 2
    if n == 0:
        return 0.0
    samples = array.array("h")
    samples.frombytes(frame[: n * 2])
    acc = 0
    for s in samples:
        acc += s * s
    return math.sqrt(acc / n)


class KioskVoiceSession:
    def __init__(
        self,
        session: KioskSession,
        ws: WebSocket,
        live_factory: Any = None,
    ) -> None:
        self.session = session
        self.ws = ws
        self._live_factory = live_factory or GeminiLiveSession
        self._stopped = asyncio.Event()
        self._audio_q: asyncio.Queue[bytes] = asyncio.Queue(maxsize=200)
        self._transcript_q: asyncio.Queue[KioskTranscriptEntry] = asyncio.Queue()
        self._live: Optional[Any] = None
        self._agent_playing = False
        self._phase_done = asyncio.Event()
        self._tasks: list[asyncio.Task] = []
        self._last_persist = time.monotonic()

    async def _send(self, payload: dict) -> None:
        payload.setdefault("ts", time.time())
        try:
            await asyncio.wait_for(self.ws.send_json(payload), timeout=_SEND_TIMEOUT)
        except Exception:
            self._stopped.set()

    async def run(self) -> None:
        try:
            msg = await asyncio.wait_for(self.ws.receive(), timeout=15.0)
        except (asyncio.TimeoutError, WebSocketDisconnect):
            return
        if msg.get("text"):
            try:
                data = json.loads(msg["text"])
                if data.get("type") != "start":
                    await self._send(ev.error("Expected {type:'start'} handshake"))
                    return
            except Exception:
                pass

        if not settings.GOOGLE_API_KEY:
            await self._send(
                ev.error("आवाज़ सेवा उपलब्ध नहीं है। कृपया दोबारा प्रयास करें।", fatal=True)
            )
            return

        await self._send(
            ev.ready(
                self.session.session_id,
                self.session.phase,
                self.session.language,
                voice_mode="gemini_live",
            )
        )

        client_task = asyncio.create_task(self._client_reader(), name="kiosk_client")
        transcript_task = asyncio.create_task(
            self._transcript_worker(), name="kiosk_transcript"
        )
        watchdog = asyncio.create_task(self._watchdog(), name="kiosk_watchdog")
        self._tasks = [client_task, transcript_task, watchdog]
        try:
            await self._run_complaint()
            await self._finalize()
        except Exception as exc:
            log.error(
                "kiosk voice failed for %s: %s",
                self.session.session_id,
                exc,
                exc_info=True,
            )
            await self._send(
                ev.error("कुछ गलत हो गया। कृपया दोबारा प्रयास करें।", fatal=True)
            )
        finally:
            await self._teardown()
            for t in self._tasks:
                t.cancel()
            await asyncio.gather(*self._tasks, return_exceptions=True)

    async def _run_complaint(self) -> None:
        await self._send(
            ev.complaint_started(self.session.session_id, self.session.language)
        )
        instruction = system_instruction(
            self.session.language,
            phone_on_record=self.session.phone,
        )
        self._phase_done = asyncio.Event()
        self._live = self._live_factory()
        await self._live.connect(
            instruction,
            language=self.session.language,
            tools=complaint_tools(),
        )
        up = asyncio.create_task(self._relay_client_to_gemini(), name="kiosk_up")
        down = asyncio.create_task(self._relay_gemini_to_client(), name="kiosk_down")
        try:
            await self._live.send_text(kickoff_text(self.session.language))
            await self._wait_phase()
        finally:
            up.cancel()
            down.cancel()
            await asyncio.gather(up, down, return_exceptions=True)
            await self._close_live()

        if not self._stopped.is_set():
            self.session.phase = "result"
            await kiosk_session_store.update(self.session)

    async def _wait_phase(self) -> None:
        while not self._stopped.is_set() and not self._phase_done.is_set():
            await asyncio.sleep(0.05)

    async def _close_live(self) -> None:
        live = self._live
        self._live = None
        self._agent_playing = False
        if live is not None:
            try:
                await live.close()
            except Exception:
                log.debug("kiosk live close failed", exc_info=True)

    async def _relay_client_to_gemini(self) -> None:
        while not self._stopped.is_set():
            try:
                frame = await asyncio.wait_for(self._audio_q.get(), timeout=0.5)
            except asyncio.TimeoutError:
                continue
            if self._live is None:
                continue
            if self._agent_playing and pcm16_rms(frame) < _DUCK_RMS_THRESHOLD:
                continue
            try:
                await self._live.send_audio(frame)
            except Exception as exc:
                log.warning("kiosk send_audio failed: %s", exc)
                return

    async def _relay_gemini_to_client(self) -> None:
        if self._live is None:
            return
        try:
            async for event in self._live.receive():
                if self._stopped.is_set():
                    return
                await self._handle_live_event(event)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log.error("kiosk gemini relay failed: %s", exc, exc_info=True)
            await self._send(ev.error("आवाज़ सत्र बाधित हो गया।"))
            self._stopped.set()

    async def _handle_live_event(self, event: LiveEvent) -> None:
        if event.kind == "user_speech_started":
            await self._send(ev.user_speech_started())
        elif event.kind == "user_transcript_partial":
            await self._send(ev.partial_transcript(to_devanagari_display(event.text)))
        elif event.kind == "user_transcript_final":
            self._enqueue_transcript("user", event.text)
            self.session.turn_count += 1
            await self._send(ev.partial_transcript(to_devanagari_display(event.text)))
        elif event.kind == "agent_audio_chunk":
            self._agent_playing = True
            b64 = base64.b64encode(event.audio).decode("ascii")
            await self._send(ev.agent_audio_chunk(b64))
        elif event.kind == "agent_transcript_partial":
            display = to_devanagari_display(event.text)
            await self._send(ev.agent_speaking(display, self.session.turn_count))
        elif event.kind == "agent_transcript_final":
            self._enqueue_transcript("agent", event.text)
            display = to_devanagari_display(event.text)
            await self._send(ev.agent_speaking(display, self.session.turn_count))
        elif event.kind == "interrupted":
            self._agent_playing = False
            await self._send(ev.interrupt())
        elif event.kind == "turn_complete":
            self._agent_playing = False
            await self._send(ev.agent_done_speaking(self.session.turn_count))
        elif event.kind == "tool_call":
            if event.tool_name == "finish_complaint":
                if self._live is not None:
                    await self._live.send_tool_response(
                        "finish_complaint",
                        event.tool_call_id,
                        {"result": "ok", "status": "closing"},
                    )
                self._phase_done.set()
            elif self._live is not None:
                await self._live.send_tool_response(
                    event.tool_name,
                    event.tool_call_id,
                    {"error": "unknown tool"},
                )
        elif event.kind == "error":
            await self._send(
                ev.error(event.error or "आवाज़ सत्र बाधित हो गया।", fatal=True)
            )
            self._stopped.set()
        elif event.kind == "go_away":
            log.info("Kiosk Gemini go_away for %s", self.session.session_id)

    async def _client_reader(self) -> None:
        while not self._stopped.is_set():
            try:
                msg = await asyncio.wait_for(self.ws.receive(), timeout=1.0)
            except asyncio.TimeoutError:
                continue
            except WebSocketDisconnect:
                self._stopped.set()
                self._phase_done.set()
                return
            except Exception:
                self._stopped.set()
                self._phase_done.set()
                return

            if msg.get("bytes"):
                frame = msg["bytes"]
                if len(frame) <= _MAX_AUDIO_FRAME_BYTES:
                    try:
                        self._audio_q.put_nowait(frame)
                    except asyncio.QueueFull:
                        pass
            elif msg.get("text"):
                try:
                    data = json.loads(msg["text"])
                except Exception:
                    continue
                if data.get("type") == "stop":
                    self._stopped.set()
                    self._phase_done.set()
                    return
                if data.get("type") == "ping":
                    await self._send({"type": "pong"})

    def _enqueue_transcript(self, speaker: str, text: str) -> None:
        text = (text or "").strip()
        if not text:
            return
        entry = KioskTranscriptEntry(speaker=speaker, text=text)  # type: ignore[arg-type]
        try:
            self._transcript_q.put_nowait(entry)
        except asyncio.QueueFull:
            self.session.transcript.append(entry)

    async def _transcript_worker(self) -> None:
        interval = settings.KIOSK_PERSIST_INTERVAL_SECS
        while not self._stopped.is_set():
            try:
                entry = await asyncio.wait_for(self._transcript_q.get(), timeout=0.5)
                self.session.transcript.append(entry)
            except asyncio.TimeoutError:
                pass
            now = time.monotonic()
            if now - self._last_persist >= interval:
                self._last_persist = now
                try:
                    await kiosk_session_store.update(self.session)
                except Exception:
                    log.debug("kiosk periodic persist failed", exc_info=True)

    async def _watchdog(self) -> None:
        limit = settings.KIOSK_MAX_SESSION_MINUTES * 60
        started = time.monotonic()
        while not self._stopped.is_set():
            if time.monotonic() - started >= limit:
                log.info(
                    "kiosk session %s hit %s min cap",
                    self.session.session_id,
                    settings.KIOSK_MAX_SESSION_MINUTES,
                )
                self._stopped.set()
                self._phase_done.set()
                return
            await asyncio.sleep(1.0)

    async def _finalize(self) -> None:
        while True:
            try:
                self.session.transcript.append(self._transcript_q.get_nowait())
            except asyncio.QueueEmpty:
                break
        try:
            await run_post_call_extract(self.session)
        except Exception as exc:
            log.error("kiosk post-call failed: %s", exc, exc_info=True)
            self.session.status = "partial"
            self.session.ended_at = datetime.utcnow()
            await kiosk_session_store.update(self.session)

        if self.session.status == "partial":
            await self._send(ev.session_partial(self.session.session_id))
            return
        grievance = (
            self.session.grievance.model_dump(mode="json")
            if self.session.grievance
            else {}
        )
        await self._send(
            ev.result_ready(self.session.complaint_number or "", grievance)
        )

    async def _teardown(self) -> None:
        await self._close_live()
        if self.session.status == "active":
            self.session.status = "partial"
            await kiosk_session_store.update(self.session)
            await self._send(ev.session_partial(self.session.session_id))
        await self._send({"type": "ended", "session_id": self.session.session_id})
