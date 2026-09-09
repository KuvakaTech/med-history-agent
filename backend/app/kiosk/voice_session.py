"""Kiosk voice session — Gemini Live for grievance and learning centres."""
from __future__ import annotations

import array
import asyncio
import base64
import json
import logging
import math
import re
import time
from datetime import datetime
from typing import Any, Optional

from fastapi import WebSocket, WebSocketDisconnect

from app.core.config import settings
from app.kiosk import events as ev
from app.kiosk.gemini_live import (
    GeminiLiveSession,
    LiveEvent,
    complaint_tools,
    lesson_tools,
    sanitize_agent_transcript,
)
from app.kiosk.hindi_display import to_devanagari_display
from app.kiosk.learning_engine import LearningEngine, agent_invites_repeat
from app.kiosk.learning_extract import run_learning_extract
from app.kiosk.models import KioskCentre, KioskSession, KioskTranscriptEntry, centre_kind_for
from app.kiosk.post_call_extract import run_post_call_extract
from app.kiosk.prompts import (
    is_jan_sunwai_v3,
    kickoff_text,
    kickoff_text_learning,
    system_instruction,
    system_instruction_learning,
)
from app.kiosk.session_store import kiosk_session_store
from app.kiosk.vocabulary import get_word_for_lesson
from app.kiosk.word_detect import detect_word_in_speech
from app.kiosk.word_matcher import answer_hint, match_answer

log = logging.getLogger(__name__)

_MAX_AUDIO_FRAME_BYTES = 64 * 1024
_SEND_TIMEOUT = 8.0
_DUCK_RMS_THRESHOLD = 600.0
_MAX_ANSWER_ATTEMPTS = 2

_TOOL_LEAK_RE = re.compile(
    r"call:finish_(?:complaint|lesson)\{.*?(?:\}|$)",
    re.IGNORECASE | re.DOTALL,
)


def _looks_like_grievance_closing(text: str) -> bool:
    low = (text or "").lower()
    thanked = any(
        p in low for p in ("धन्यवाद", "dhanyavaad", "dhanyawad", "thank you")
    )
    if not thanked:
        return False
    return any(
        p in low
        for p in (
            "शुभ हो",
            "din shubh",
            "good day",
            "nice day",
            "जन सुनवाई",
            "jan sunwai",
            "दर्ज कर ली",
            "दर्ज हो",
            "darj ho",
            "darj kar",
            "recorded",
            "नोट कर",
            "जानकारी",
            "jaankari",
            "parchi print",
            "print ho rahi",
            "print ho raha",
            "ghar par",
            "aaram se dekh",
        )
    )

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
        centre: KioskCentre,
        live_factory: Any = None,
    ) -> None:
        self.session = session
        self.centre = centre
        self.ws = ws
        self._live_factory = live_factory or GeminiLiveSession
        self._is_learning = centre_kind_for(centre) == "learning"
        self._finish_tool = "finish_lesson" if self._is_learning else "finish_complaint"
        self._stopped = asyncio.Event()
        self._audio_q: asyncio.Queue[bytes] = asyncio.Queue(maxsize=200)
        self._transcript_q: asyncio.Queue[KioskTranscriptEntry] = asyncio.Queue()
        self._live: Optional[Any] = None
        self._agent_playing = False
        self._phase_done = asyncio.Event()
        self._tasks: list[asyncio.Task] = []
        self._last_persist = time.monotonic()
        self._displayed_card: Optional[dict[str, str]] = None
        self._awaiting_user = False
        self._awaiting_child_answer = False
        self._answer_attempts = 0
        self._last_answer_result: Optional[str] = None
        self._agent_turn_id = 0
        self._last_answer_turn_id = -1
        self._closing_turn_count = 0
        self._learning_engine: Optional[LearningEngine] = None
        if self._is_learning:
            self._learning_engine = LearningEngine(session.lesson_topic)

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
            await self._run_voice_phase()
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

    async def _run_voice_phase(self) -> None:
        if self._is_learning:
            await self._send(ev.lesson_started(self.session.session_id, self.session.language))
            instruction = system_instruction_learning(
                self.centre,
                self.session.language,
                self.session.learner_name,
                self.session.lesson_topic,
            )
            tools = lesson_tools()
            kickoff = kickoff_text_learning(
                self.centre,
                self.session.language,
                self.session.learner_name,
                self.session.lesson_topic,
            )
        else:
            await self._send(
                ev.complaint_started(self.session.session_id, self.session.language)
            )
            instruction = system_instruction(
                self.centre,
                self.session.language,
                phone_on_record=self.session.phone,
            )
            tools = complaint_tools(v3=is_jan_sunwai_v3(self.centre))
            kickoff = kickoff_text(self.centre, self.session.language)

        self._phase_done = asyncio.Event()
        self._live = self._live_factory()
        await self._live.connect(
            instruction,
            language=self.session.language,
            tools=tools,
            learning=self._is_learning,
        )
        up = asyncio.create_task(self._relay_client_to_gemini(), name="kiosk_up")
        down = asyncio.create_task(self._relay_gemini_to_client(), name="kiosk_down")
        try:
            await self._live.send_text(kickoff)
            await self._wait_phase()
        finally:
            up.cancel()
            down.cancel()
            await asyncio.gather(up, down, return_exceptions=True)
            await self._close_live()

        if not self._stopped.is_set():
            await self._send(ev.session_processing(self.session.session_id))
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
            if (
                not self._is_learning
                and self._agent_playing
                and pcm16_rms(frame) < _DUCK_RMS_THRESHOLD
            ):
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
                if self._stopped.is_set() or self._phase_done.is_set():
                    return
                await self._handle_live_event(event)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log.error("kiosk gemini relay failed: %s", exc, exc_info=True)
            await self._send(ev.error("आवाज़ सत्र बाधित हो गया।"))
            self._stopped.set()

    async def _handle_live_event(self, event: LiveEvent) -> None:
        if self._phase_done.is_set() and event.kind in (
            "agent_audio_chunk",
            "agent_transcript_partial",
            "agent_transcript_final",
            "turn_complete",
        ):
            return
        if event.kind == "user_speech_started":
            await self._send(ev.user_speech_started())
        elif event.kind == "user_transcript_partial":
            await self._send(ev.partial_transcript(to_devanagari_display(event.text)))
        elif event.kind == "user_transcript_final":
            await self._handle_user_transcript_final(event.text)
        elif event.kind == "agent_audio_chunk":
            self._agent_playing = True
            b64 = base64.b64encode(event.audio).decode("ascii")
            await self._send(ev.agent_audio_chunk(b64))
        elif event.kind == "agent_transcript_partial":
            text = sanitize_agent_transcript(event.text)
            if not text:
                return
            display = to_devanagari_display(text)
            await self._send(ev.agent_speaking(display, self.session.turn_count))
        elif event.kind == "agent_transcript_final":
            text = sanitize_agent_transcript(event.text)
            if not text:
                return
            self._enqueue_transcript("agent", text)
            display = to_devanagari_display(text)
            await self._send(ev.agent_speaking(display, self.session.turn_count))
            await self._on_agent_transcript_final(text)
        elif event.kind == "interrupted":
            self._agent_playing = False
            await self._send(ev.interrupt())
        elif event.kind == "turn_complete":
            self._agent_playing = False
            self._agent_turn_id += 1
            self._awaiting_user = True
            await self._send(ev.agent_done_speaking(self.session.turn_count))
        elif event.kind == "tool_call":
            if event.tool_name == self._finish_tool:
                await self._handle_finish_tool(event)
            elif event.tool_name == "show_word_card" and self._is_learning:
                await self._handle_show_word_card(event)
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

    async def _handle_user_transcript_final(self, text: str) -> None:
        display = to_devanagari_display(text)
        self._enqueue_transcript("user", text)
        self.session.turn_count += 1
        await self._send(ev.partial_transcript(display))

        if self._is_learning and self._learning_engine and self.session.turn_count == 1:
            self._learning_engine.on_intro_complete()
            await self._engine_emit_expected_card()
            self._persist_lesson_snapshot()
            if self._live is not None:
                hint = self._learning_engine.next_word_private_hint()
                if hint:
                    await self._live.send_text(hint)

        if not self._awaiting_user:
            return

        if self._last_answer_turn_id == self._agent_turn_id:
            return

        self._awaiting_user = False
        await self._process_child_answer(text)

    async def _on_agent_transcript_final(self, text: str) -> None:
        if self._is_learning:
            await self._maybe_auto_show_card(text)
            if self._displayed_card and agent_invites_repeat(text):
                self._awaiting_child_answer = True
                self._answer_attempts = 0
                self._last_answer_result = None
            return
        await self._maybe_auto_finish_on_closing(text)

    async def _maybe_auto_finish_on_closing(self, text: str) -> None:
        if self._phase_done.is_set():
            return
        if _TOOL_LEAK_RE.search(text):
            log.info(
                "kiosk auto-finish on leaked finish tool for %s",
                self.session.session_id,
            )
            self._phase_done.set()
            return
        if not _looks_like_grievance_closing(text):
            self._closing_turn_count = 0
            return
        self._closing_turn_count += 1
        if self._closing_turn_count >= 1:
            log.info(
                "kiosk auto-finish on closing transcript for %s",
                self.session.session_id,
            )
            self._phase_done.set()

    async def _process_child_answer(self, transcript: str) -> None:
        """Unified teach + quiz verification against the displayed card."""
        if not self._is_learning or not self._awaiting_child_answer:
            return
        if not self._displayed_card:
            return

        text = (transcript or "").strip()
        if not text:
            return

        word_id = self._displayed_card["word_id"]
        word = get_word_for_lesson(word_id, self.session.lesson_topic)
        if word is None:
            return

        self._last_answer_turn_id = self._agent_turn_id
        result = match_answer(text, word_id)
        self._last_answer_result = result
        await self._send(
            ev.word_answer_result(word_id, text, result, word.hindi)
        )
        if self._live is not None:
            await self._live.send_text(answer_hint(result, word, text))

        self._answer_attempts += 1
        word_done = result in ("clear", "close") or self._answer_attempts >= _MAX_ANSWER_ATTEMPTS

        if self._learning_engine and word_done:
            engine = self._learning_engine
            if engine.phase == "recall":
                if engine.record_answer(word_id, result):
                    engine.advance_recall()
                    self._awaiting_child_answer = False
                    self._answer_attempts = 0
                    self._persist_lesson_snapshot()
                    await self._engine_emit_expected_card()
                    if self._live is not None:
                        hint = engine.next_word_private_hint()
                        if hint:
                            await self._live.send_text(hint)
            elif engine.record_answer(word_id, result):
                engine.advance_word()
                self._awaiting_child_answer = False
                self._answer_attempts = 0
                self._persist_lesson_snapshot()
                await self._engine_emit_expected_card()
                if self._live is not None:
                    hint = engine.next_word_private_hint()
                    if hint:
                        await self._live.send_text(hint)
        elif word_done:
            self._awaiting_child_answer = False
            self._answer_attempts = 0

    async def _emit_word_card(self, word_id: str, mode: str) -> bool:
        word = get_word_for_lesson(word_id, self.session.lesson_topic)
        if word is None:
            return False
        self._displayed_card = {"word_id": word.word_id, "mode": mode}
        self._answer_attempts = 0
        self._last_answer_result = None
        if mode == "quiz":
            self._awaiting_child_answer = True
        else:
            self._awaiting_child_answer = False
        await self._send(
            ev.show_word_card(word.word_id, word.hindi, word.image, mode)
        )
        return True

    def _persist_lesson_snapshot(self) -> None:
        if self._learning_engine is not None:
            self.session.lesson_state = self._learning_engine.to_snapshot()

    async def _engine_emit_expected_card(self) -> None:
        engine = self._learning_engine
        if engine is None or engine.phase == "intro":
            return
        word_id = engine.expected_word_id()
        if not word_id:
            return
        mode = engine.expected_card_mode()
        await self._emit_word_card(word_id, mode)

    async def _maybe_auto_show_card(self, text: str) -> None:
        if not self._is_learning:
            return
        if self.session.turn_count < 1:
            return

        detected = detect_word_in_speech(text, self.session.lesson_topic)
        if not detected:
            return
        word_id, default_mode = detected
        displayed_id = (self._displayed_card or {}).get("word_id")
        if displayed_id == word_id:
            return

        if (
            self._awaiting_child_answer
            and displayed_id
            and word_id != displayed_id
            and self._last_answer_result == "wrong"
            and self._answer_attempts < _MAX_ANSWER_ATTEMPTS
        ):
            return

        engine = self._learning_engine
        mode = default_mode
        if engine:
            if engine.phase == "intro" and self.session.turn_count >= 1:
                engine.on_intro_complete()
            if engine.phase == "recall":
                expected = engine.current_recall_word()
                if word_id != expected:
                    return
                mode = "quiz"
            elif not engine.sync_to_word(word_id):
                return
            else:
                mode = engine.expected_card_mode()
        elif self._awaiting_child_answer:
            return

        await self._emit_word_card(word_id, mode)
        self._persist_lesson_snapshot()

    async def _handle_show_word_card(self, event: LiveEvent) -> None:
        word_id = str((event.tool_args or {}).get("word_id") or "").strip().lower()
        mode = str((event.tool_args or {}).get("mode") or "teach").strip().lower()
        if mode not in ("teach", "quiz"):
            mode = "teach"

        if self._learning_engine is not None:
            validation_err = self._learning_engine.validate_show_word_card(word_id, mode)
            if validation_err:
                if self._live is not None:
                    await self._live.send_tool_response(
                        "show_word_card",
                        event.tool_call_id,
                        {"error": validation_err},
                    )
                    expected = self._learning_engine.expected_word_id()
                    await self._live.send_text(
                        f"[SYSTEM — private] show_word_card rejected: {validation_err}. "
                        f"Use word_id={expected} mode={self._learning_engine.expected_card_mode()}."
                    )
                return
            if self._learning_engine.phase not in ("intro", "recall", "close"):
                self._learning_engine.sync_to_word(word_id)

        ok = await self._emit_word_card(word_id, mode)
        if ok:
            self._persist_lesson_snapshot()
        if not ok:
            if self._live is not None:
                await self._live.send_tool_response(
                    "show_word_card",
                    event.tool_call_id,
                    {"error": f"unknown word_id: {word_id}"},
                )
            return

        word = get_word_for_lesson(word_id, self.session.lesson_topic)
        if self._live is not None and word is not None:
            await self._live.send_tool_response(
                "show_word_card",
                event.tool_call_id,
                {"result": "ok", "hindi": word.hindi, "word_id": word.word_id},
            )

    async def _inject_test_utterance(self, text: str) -> None:
        """Test-only: send citizen text to Gemini Live (no microphone)."""
        self._enqueue_transcript("user", text)
        if self._live is not None:
            await self._live.send_text(text)

    async def _handle_finish_tool(self, event: LiveEvent) -> None:
        if (
            self._is_learning
            and self._learning_engine
            and not self._learning_engine.can_finish_lesson()
        ):
            if self._live is not None:
                await self._live.send_tool_response(
                    self._finish_tool,
                    event.tool_call_id,
                    {"error": "lesson not complete — teach more words first"},
                )
                await self._live.send_text(self._learning_engine.finish_rejected_hint())
            return

        if self._live is not None:
            await self._live.send_tool_response(
                self._finish_tool,
                event.tool_call_id,
                {"result": "ok", "status": "closing"},
            )
        if not self._is_learning:
            args = event.tool_args or {}
            session_type = args.get("session_type")
            print_mode = args.get("print_mode")
            if session_type:
                self.session.finish_session_type = str(session_type).strip()
            if print_mode:
                self.session.finish_print_mode = str(print_mode).strip()
        self._phase_done.set()

    def _enqueue_audio_frame(self, frame: bytes) -> None:
        try:
            self._audio_q.put_nowait(frame)
        except asyncio.QueueFull:
            try:
                self._audio_q.get_nowait()
            except asyncio.QueueEmpty:
                pass
            try:
                self._audio_q.put_nowait(frame)
            except asyncio.QueueFull:
                log.warning("kiosk audio queue full — dropping frame")

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
                    self._enqueue_audio_frame(frame)
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
                elif (
                    data.get("type") == "test_utterance"
                    and settings.KIOSK_TEST_UTTERANCE_ENABLED
                    and not self._is_learning
                ):
                    text = (data.get("text") or "").strip()
                    if text:
                        await self._inject_test_utterance(text)

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
        if self._learning_engine is not None:
            self._persist_lesson_snapshot()
        try:
            if self._is_learning:
                await run_learning_extract(self.session, self.centre)
            else:
                await run_post_call_extract(self.session, self.centre)
        except Exception as exc:
            log.error("kiosk post-call failed: %s", exc, exc_info=True)
            self.session.status = "partial"
            self.session.ended_at = datetime.utcnow()
            await kiosk_session_store.update(self.session)

        if self.session.status == "partial":
            await self._send(ev.session_partial(self.session.session_id))
            return

        if self._is_learning:
            record = (
                self.session.learning_record.model_dump(mode="json")
                if self.session.learning_record
                else {}
            )
            await self._send(ev.result_ready(learning_record=record))
        else:
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
