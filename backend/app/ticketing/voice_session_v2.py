"""TicketVoiceSessionV2 — Gemini Live orchestrator for ticketing voice.

Replaces the v1 per-turn Deepgram → Haiku → ElevenLabs loop when
TICKETING_USE_GEMINI_LIVE=true. Same browser WebSocket; frontend branches on
ready.voice_mode=gemini_live.

Not copied from v1: mic gate, silence-retry re-ask loop, per-turn TTS.
"""

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
from app.ticketing import events as ev
from app.ticketing.gemini_live import (
    GeminiLiveSession,
    LiveEvent,
    consultation_tools,
    triage_tools,
)
from app.ticketing.models import CategoryInfo, TicketSession, TicketTranscriptEntry
from app.ticketing.post_call_extract import (
    extract_triage_fallback,
    format_transcript,
    run_post_call_extract,
)
from app.ticketing.prompts_v2 import (
    consultation_kickoff_text,
    consultation_system_instruction,
    triage_kickoff_text,
    triage_system_instruction,
)
from app.ticketing.session_store import ticket_session_store
from app.ticketing.triage_engine import MAX_TRIAGE_TURNS

log = logging.getLogger(__name__)

_MAX_AUDIO_FRAME_BYTES = 64 * 1024
_SEND_TIMEOUT = 8.0
_DUCK_RMS_THRESHOLD = 600.0
_TRIAGE_TURN_CEILING = MAX_TRIAGE_TURNS
_CONSULT_TURN_CEILING = 12

_live_counts: dict[str, int] = {}
_live_lock = asyncio.Lock()


def reset_live_slots() -> None:
    """Test helper — drop in-process occupancy."""
    _live_counts.clear()


async def acquire_live_slot(hospital_id: str) -> bool:
    cap = settings.TICKETING_MAX_CONCURRENT_LIVE_SESSIONS_PER_HOSPITAL
    async with _live_lock:
        n = _live_counts.get(hospital_id, 0)
        if n >= cap:
            return False
        _live_counts[hospital_id] = n + 1
        return True


async def release_live_slot(hospital_id: str) -> None:
    async with _live_lock:
        n = _live_counts.get(hospital_id, 0)
        if n <= 1:
            _live_counts.pop(hospital_id, None)
        else:
            _live_counts[hospital_id] = n - 1


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


class TicketVoiceSessionV2:
    def __init__(
        self,
        session: TicketSession,
        ws: WebSocket,
        categories: list,
        live_factory: Any = None,
    ) -> None:
        self.session = session
        self.ws = ws
        self.categories = categories
        self._live_factory = live_factory or GeminiLiveSession
        self._stopped = asyncio.Event()
        self._audio_q: asyncio.Queue[bytes] = asyncio.Queue(maxsize=200)
        self._transcript_q: asyncio.Queue[TicketTranscriptEntry] = asyncio.Queue()
        self._live: Optional[Any] = None
        self._relay_paused = False
        self._agent_playing = False
        self._phase_done = asyncio.Event()
        self._pending_category: Optional[dict] = None
        self._category_key: Optional[str] = None
        self._category_label: Optional[str] = None
        self._patient_name: str = "the patient"
        self._patient_age: str = "unknown"
        self._routing_summary: str = ""
        self._user_turns_this_phase = 0
        self._tasks: list[asyncio.Task] = []
        self._last_persist = time.monotonic()
        self._valid_keys = {c.key: c.label for c in categories}
        self._triage_ceiling_fired = False

    # ── Wire ───────────────────────────────────────────────────

    async def _send(self, payload: dict) -> None:
        payload.setdefault("ts", time.time())
        try:
            await asyncio.wait_for(self.ws.send_json(payload), timeout=_SEND_TIMEOUT)
        except Exception:
            self._stopped.set()

    # ── Entry ──────────────────────────────────────────────────

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
                ev.error("Voice is unavailable. Please try again.", fatal=True)
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

        client_task = asyncio.create_task(self._client_reader(), name="v2_client")
        transcript_task = asyncio.create_task(
            self._transcript_worker(), name="v2_transcript"
        )
        watchdog = asyncio.create_task(self._watchdog(), name="v2_watchdog")
        self._tasks = [client_task, transcript_task, watchdog]
        try:
            await self._run_triage()
            if not self._stopped.is_set() and self._category_key:
                await self._run_consultation()
            # Always extract if we got any audio — stop/timeout still produce a report.
            await self._finalize()
        except Exception as exc:
            log.error(
                "voice_session_v2 failed for %s: %s",
                self.session.session_id,
                exc,
                exc_info=True,
            )
            await self._send(
                ev.error("Something went wrong. Please try again.", fatal=True)
            )
        finally:
            await self._teardown()
            for t in self._tasks:
                t.cancel()
            await asyncio.gather(*self._tasks, return_exceptions=True)

    # ── Phases ─────────────────────────────────────────────────

    async def _run_triage(self) -> None:
        await self._send(
            ev.triage_started(self.session.session_id, self.session.language)
        )
        instruction = triage_system_instruction(
            self.categories, self.session.language, self.session.gender
        )
        self._phase_done = asyncio.Event()
        self._user_turns_this_phase = 0
        self._live = self._live_factory()
        await self._live.connect(
            instruction,
            language=self.session.language,
            tools=triage_tools(),
        )
        up = asyncio.create_task(self._relay_client_to_gemini(), name="v2_up_triage")
        down = asyncio.create_task(
            self._relay_gemini_to_client("triage"), name="v2_down_triage"
        )
        try:
            await self._live.send_text(triage_kickoff_text(self.session.language))
            await self._wait_phase()
        finally:
            up.cancel()
            down.cancel()
            await asyncio.gather(up, down, return_exceptions=True)
            await self._close_live()

        if self._stopped.is_set():
            return
        if self._category_key:
            self.session.category = CategoryInfo(
                key=self._category_key,
                label=self._category_label or self._category_key,
                source="auto",
            )
            self.session.phase = "consultation"
            await ticket_session_store.update(self.session)
            await self._send(
                ev.consultation_started(self._category_key, self.session.turn_count)
            )
            return

        cats = [{"key": c.key, "label": c.label} for c in self.categories]
        await self._send(ev.category_manual_required(cats))
        cat = await self._wait_for_category_selection()
        if not cat:
            return
        self._category_key = cat["key"]
        self._category_label = cat["label"]
        self.session.category = CategoryInfo(
            key=cat["key"], label=cat["label"], source="manual"
        )
        self.session.phase = "consultation"
        await ticket_session_store.update(self.session)
        await self._send(ev.category_confirmed(cat["key"], cat["label"], "manual"))
        await self._send(ev.consultation_started(cat["key"], self.session.turn_count))

    async def _run_consultation(self) -> None:
        label = self._category_label or self._category_key or "General Medicine"
        instruction = consultation_system_instruction(
            category_label=label,
            language=self.session.language,
            name=self._patient_name,
            age=self._patient_age,
            gender=self.session.gender,
            routing_summary=self._routing_summary,
        )
        self._phase_done = asyncio.Event()
        self._user_turns_this_phase = 0
        self._drain_audio_q()
        self._live = self._live_factory()
        await self._live.connect(
            instruction,
            language=self.session.language,
            tools=consultation_tools(),
        )
        up = asyncio.create_task(self._relay_client_to_gemini(), name="v2_up_consult")
        down = asyncio.create_task(
            self._relay_gemini_to_client("consultation"), name="v2_down_consult"
        )
        try:
            await self._live.send_text(
                consultation_kickoff_text(self.session.language, self._routing_summary)
            )
            await self._wait_phase()
        finally:
            up.cancel()
            down.cancel()
            await asyncio.gather(up, down, return_exceptions=True)
            await self._close_live()

        if not self._stopped.is_set():
            await self._send(ev.consultation_ended())
            self.session.phase = "result"
            await ticket_session_store.update(self.session)

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
                log.debug("live close failed", exc_info=True)

    def _drain_audio_q(self) -> None:
        while True:
            try:
                self._audio_q.get_nowait()
            except asyncio.QueueEmpty:
                return

    # ── Relays ─────────────────────────────────────────────────

    async def _relay_client_to_gemini(self) -> None:
        while not self._stopped.is_set():
            try:
                frame = await asyncio.wait_for(self._audio_q.get(), timeout=0.5)
            except asyncio.TimeoutError:
                continue
            if self._relay_paused or self._live is None:
                continue
            if self._agent_playing and pcm16_rms(frame) < _DUCK_RMS_THRESHOLD:
                continue
            try:
                await self._live.send_audio(frame)
            except Exception as exc:
                log.warning("send_audio failed: %s", exc)
                return

    async def _relay_gemini_to_client(self, phase: str) -> None:
        if self._live is None:
            return
        try:
            async for event in self._live.receive():
                if self._stopped.is_set():
                    return
                await self._handle_live_event(event, phase)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log.error("gemini relay failed: %s", exc, exc_info=True)
            await self._send(ev.error("Voice session interrupted."))
            self._stopped.set()

    async def _handle_live_event(self, event: LiveEvent, phase: str) -> None:
        if event.kind == "user_speech_started":
            await self._send(ev.user_speech_started())
        elif event.kind == "user_transcript_partial":
            await self._send(ev.partial_transcript(event.text))
        elif event.kind == "user_transcript_final":
            self._enqueue_transcript("user", event.text)
            self.session.turn_count += 1
            self._user_turns_this_phase += 1
            await self._send(ev.partial_transcript(event.text))
            if (
                phase == "triage"
                and self._user_turns_this_phase >= _TRIAGE_TURN_CEILING
            ):
                await self._triage_turn_ceiling()
            elif (
                phase == "consultation"
                and self._user_turns_this_phase >= _CONSULT_TURN_CEILING
            ):
                self._phase_done.set()
        elif event.kind == "agent_audio_chunk":
            self._agent_playing = True
            b64 = base64.b64encode(event.audio).decode("ascii")
            await self._send(ev.agent_audio_chunk(b64))
        elif event.kind == "agent_transcript_partial":
            await self._send(ev.agent_speaking(event.text, self.session.turn_count))
        elif event.kind == "agent_transcript_final":
            self._enqueue_transcript("agent", event.text)
            await self._send(ev.agent_speaking(event.text, self.session.turn_count))
        elif event.kind == "interrupted":
            self._agent_playing = False
            await self._send(ev.interrupt())
        elif event.kind == "turn_complete":
            self._agent_playing = False
            await self._send(ev.agent_done_speaking(self.session.turn_count))
        elif event.kind == "tool_call":
            await self._handle_tool(event, phase)
        elif event.kind == "error":
            await self._send(
                ev.error(event.error or "Voice session interrupted.", fatal=True)
            )
            self._stopped.set()
        elif event.kind == "go_away":
            log.info("Gemini Live go_away for session %s", self.session.session_id)

    async def _handle_tool(self, event: LiveEvent, phase: str) -> None:
        name = event.tool_name
        args = event.tool_args or {}
        if name == "finish_triage" and phase == "triage":
            await self._on_finish_triage(args, event.tool_call_id)
        elif name == "finish_consultation" and phase == "consultation":
            if self._live is not None:
                await self._live.send_tool_response(
                    name, event.tool_call_id, {"result": "ok", "status": "closing"}
                )
            self._phase_done.set()
        elif self._live is not None:
            await self._live.send_tool_response(
                name, event.tool_call_id, {"error": "unknown tool for this phase"}
            )

    async def _on_finish_triage(self, args: dict, call_id: Optional[str]) -> None:
        name = str(args.get("patient_name") or "").strip() or "the patient"
        age = args.get("patient_age")
        summary = str(args.get("routing_summary") or "").strip()
        key = str(args.get("category_key") or "").strip()
        confidence = str(args.get("confidence") or "low").lower()
        self._patient_name = name
        if age is not None:
            try:
                self._patient_age = str(int(age))
            except (TypeError, ValueError):
                self._patient_age = str(age)
        self._routing_summary = summary

        accepted = key in self._valid_keys and confidence in ("high", "medium")
        if accepted:
            self._category_key = key
            self._category_label = self._valid_keys[key]
            await self._send(
                ev.category_identified(key, self._category_label, confidence)
            )
            if self._live is not None:
                await self._live.send_tool_response(
                    "finish_triage",
                    call_id,
                    {
                        "result": "ok",
                        "status": "handoff",
                        "department": self._category_label,
                    },
                )
            self._phase_done.set()
            return

        if self._live is not None:
            await self._live.send_tool_response(
                "finish_triage",
                call_id,
                {
                    "result": "rejected",
                    "reason": "category not valid or confidence too low; keep talking or we will show a picker",
                },
            )
        if self._user_turns_this_phase >= _TRIAGE_TURN_CEILING:
            self._phase_done.set()

    async def _triage_turn_ceiling(self) -> None:
        if (
            self._triage_ceiling_fired
            or self._phase_done.is_set()
            or self._category_key
        ):
            return
        self._triage_ceiling_fired = True
        transcript = format_transcript(self.session.transcript)
        keys = ", ".join(f'"{c.key}"' for c in self.categories)
        meta = await extract_triage_fallback(transcript, keys)
        if meta.patient_name:
            self._patient_name = meta.patient_name
        if meta.patient_age is not None:
            self._patient_age = str(meta.patient_age)
        guess = meta.category_guess
        if guess and guess in self._valid_keys and meta.category_confidence != "none":
            self._category_key = guess
            self._category_label = meta.category_label or self._valid_keys[guess]
            self._routing_summary = transcript[-400:]
            await self._send(
                ev.category_identified(
                    guess, self._category_label, meta.category_confidence
                )
            )
        self._phase_done.set()

    # ── Client WS ──────────────────────────────────────────────

    async def _client_reader(self) -> None:
        while not self._stopped.is_set():
            try:
                msg = await asyncio.wait_for(self.ws.receive(), timeout=1.0)
            except asyncio.TimeoutError:
                continue
            except WebSocketDisconnect:
                self._stopped.set()
                return
            except Exception:
                self._stopped.set()
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
                mtype = data.get("type")
                if mtype == "stop":
                    self._stopped.set()
                    self._phase_done.set()
                    return
                if mtype == "ping":
                    await self._send({"type": "pong"})
                elif mtype == "category_selected":
                    self._pending_category = data

    async def _wait_for_category_selection(self) -> Optional[dict]:
        self._relay_paused = True
        self._pending_category = None
        deadline = time.monotonic() + 120.0
        while time.monotonic() < deadline and not self._stopped.is_set():
            if self._pending_category:
                cat = self._pending_category
                self._pending_category = None
                self._relay_paused = False
                key = cat.get("key", "")
                label = cat.get("label") or self._valid_keys.get(key, key)
                return {"key": key, "label": label}
            await asyncio.sleep(0.1)
        self._relay_paused = False
        return None

    # ── Transcript + persist ───────────────────────────────────

    def _enqueue_transcript(self, speaker: str, text: str) -> None:
        text = (text or "").strip()
        if not text:
            return
        entry = TicketTranscriptEntry(speaker=speaker, text=text)  # type: ignore[arg-type]
        try:
            self._transcript_q.put_nowait(entry)
        except asyncio.QueueFull:
            self.session.transcript.append(entry)

    async def _transcript_worker(self) -> None:
        interval = settings.TICKETING_PERSIST_INTERVAL_SECS
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
                    await ticket_session_store.update(self.session)
                except Exception:
                    log.debug("periodic persist failed", exc_info=True)

    async def _watchdog(self) -> None:
        limit = settings.TICKETING_MAX_SESSION_MINUTES * 60
        started = time.monotonic()
        while not self._stopped.is_set():
            if time.monotonic() - started >= limit:
                log.info(
                    "ticketing v2 session %s hit %s min cap",
                    self.session.session_id,
                    settings.TICKETING_MAX_SESSION_MINUTES,
                )
                self._stopped.set()
                self._phase_done.set()
                return
            await asyncio.sleep(1.0)

    # ── Finalize ───────────────────────────────────────────────

    async def _finalize(self) -> None:
        # Drain remaining transcript entries before extract
        while True:
            try:
                self.session.transcript.append(self._transcript_q.get_nowait())
            except asyncio.QueueEmpty:
                break
        try:
            await run_post_call_extract(self.session, self.categories)
        except Exception as exc:
            log.error("post-call extract failed: %s", exc, exc_info=True)
            self.session.status = "partial"
            self.session.ended_at = datetime.utcnow()
            await ticket_session_store.update(self.session)

        if self.session.status == "partial":
            await self._send(ev.session_partial(self.session.session_id))
            return
        flags_json = [f.model_dump(mode="json") for f in self.session.flags]
        await self._send(ev.result_ready(self.session.summary, flags_json))

    async def _teardown(self) -> None:
        await self._close_live()
        if self.session.status == "active":
            self.session.status = "partial"
            await ticket_session_store.update(self.session)
            await self._send(ev.session_partial(self.session.session_id))
        await self._send({"type": "ended", "session_id": self.session.session_id})
