"""TicketVoiceSession — orchestrates one continuous voice call for a ticket.

Flow per turn:
  1. Patient speaks → Deepgram real-time STT streams back interim text
  2. UtteranceEnd fires (patient stopped speaking)
  3. Final transcript assembled → LLM turn (triage or consultation)
  4. LLM streams question tokens → TTS synthesizes → MP3 sent to FE as base64
  5. FE plays audio → agent_done_speaking event → mic re-opens

No barge-in: the mic is gated. The FE only streams audio while the gate is open.
The server opens the gate by sending agent_done_speaking.

WebSocket message protocol:
  Client → Server:
    binary frames   — raw PCM16 16kHz audio (while gate is open)
    {"type":"start"}                — handshake, begins session
    {"type":"stop"}                 — graceful end
    {"type":"category_selected","key":"gynecology"} — manual category pick
    {"type":"ping"}

  Server → Client:
    {"type":"ready", ...}           — session ready, gate open for first turn
    {"type":"partial_transcript","text":"..."} — live STT interim
    {"type":"agent_speaking","question":"...","turn":N,"audio_b64":"..."} — TTS audio
    {"type":"agent_done_speaking","turn":N} — gate opens
    {"type":"turn_complete",...}    — full turn metadata
    plus all structured events from events.py (triage_started, category_identified, etc.)
    {"type":"error","message":"...","fatal":bool}
    {"type":"ended","session_id":"..."}
    {"type":"pong"}
"""
from __future__ import annotations

import asyncio
import base64
import json
import logging
import time
from typing import Optional

from fastapi import WebSocket, WebSocketDisconnect

from app.agent import llm
from app.agent.summarization.service import SummarizationService
from app.ticketing import events as ev
from app.ticketing.consultation_engine import ConsultationEngine
from app.ticketing.deepgram_live import DeepgramLiveStream, DGEventType
from app.ticketing.models import (
    CategoryInfo,
    TicketQAEntry,
    TicketSession,
)
from app.ticketing.session_store import ticket_session_store
from app.ticketing.triage_engine import TriageEngine
from app.ticketing.tts_service import synthesize_ticket

log = logging.getLogger(__name__)

_MAX_AUDIO_FRAME_BYTES = 64 * 1024
_KEEPALIVE_INTERVAL = 10.0  # seconds between Deepgram keepalives
_SEND_TIMEOUT = 8.0


class TicketVoiceSession:
    def __init__(
        self,
        session: TicketSession,
        ws: WebSocket,
        categories: list,  # list[TicketCategory]
    ) -> None:
        self.session = session
        self.ws = ws
        self.categories = categories
        self._stopped = asyncio.Event()
        self._audio_q: asyncio.Queue[bytes] = asyncio.Queue(maxsize=200)
        self._dg: Optional[DeepgramLiveStream] = None
        self._triage_covered: list[str] = []
        self._consult_covered: list[str] = []
        # Resolved after triage
        self._category_key: Optional[str] = None
        self._category_label: Optional[str] = None
        self._patient_name: str = "the patient"
        self._patient_age: str = "unknown"
        # Gate: True = mic is open (patient may speak)
        self._mic_open = False
        # Current final transcript assembled from Deepgram
        self._utterance_buf: list[str] = []

    # ── Wire helpers ───────────────────────────────────────────

    async def _send(self, payload: dict) -> None:
        payload.setdefault("ts", time.time())
        try:
            await asyncio.wait_for(self.ws.send_json(payload), timeout=_SEND_TIMEOUT)
        except Exception:
            self._stopped.set()

    async def _send_bytes(self, data: bytes) -> None:
        try:
            await asyncio.wait_for(self.ws.send_bytes(data), timeout=_SEND_TIMEOUT)
        except Exception:
            self._stopped.set()

    async def _send_audio(self, mp3_bytes: bytes, question: str, turn: int) -> None:
        """Send TTS audio as base64 JSON — avoids binary framing complexity."""
        await self._send({
            "type": "agent_speaking",
            "question": question,
            "turn": turn,
            "audio_b64": base64.b64encode(mp3_bytes).decode("ascii"),
            "mime": "audio/mpeg",
        })

    # ── Main entry ─────────────────────────────────────────────

    async def run(self) -> None:
        # Wait for handshake
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

        # Connect Deepgram
        self._dg = DeepgramLiveStream(language=self.session.language)
        try:
            await self._dg.connect()
        except Exception as exc:
            log.error("Deepgram connect failed for session %s: %s", self.session.session_id, exc)
            await self._send(ev.error("Voice transcription unavailable. Please try again.", fatal=True))
            return

        await self._send({
            "type": "ready",
            "session_id": self.session.session_id,
            "phase": self.session.phase,
            "language": self.session.language,
        })

        # Kick off triage
        await self._run_triage()

        if not self._stopped.is_set() and self.session.phase == "consultation":
            await self._run_consultation()

        if not self._stopped.is_set():
            await self._finalize()

        await self._teardown()

    # ── Triage phase ───────────────────────────────────────────

    async def _run_triage(self) -> None:
        await self._send(ev.triage_started(self.session.session_id, self.session.language))

        engine = TriageEngine(
            categories=self.categories,
            language=self.session.language,
            gender=self.session.gender,
        )

        # Opening question
        try:
            opening = await engine.opening_question()
        except Exception as exc:
            log.error("Triage opening question failed: %s", exc)
            await self._send(ev.error("Could not start triage. Please try again.", fatal=True))
            return

        await self._speak_and_wait(opening, turn=0)
        if self._stopped.is_set():
            return

        from app.ticketing.triage_engine import MAX_TRIAGE_TURNS

        for turn_idx in range(MAX_TRIAGE_TURNS):
            if self._stopped.is_set():
                return

            # Open mic and collect patient answer
            answer = await self._collect_patient_answer()
            if answer is None:  # connection dropped or stop
                return

            # Record Q&A
            current_q = self.session.qa_log[-1].question_text if self.session.qa_log else opening
            self.session.qa_log.append(TicketQAEntry(
                question_id=f"triage_{turn_idx + 1}",
                question_text=current_q,
                answer=answer,
            ))
            self.session.turn_count += 1

            # Stream next turn
            done_data = await self._stream_triage_turn(engine, answer, turn_idx)
            if done_data is None:
                return

            # Apply extracted data
            if done_data.get("patient_name"):
                self._patient_name = done_data["patient_name"]
            if done_data.get("patient_age"):
                self._patient_age = str(done_data["patient_age"])

            # Handle category result
            cat_key = done_data.get("category_guess")
            cat_label = done_data.get("category_label")
            confidence = done_data.get("category_confidence", "none")

            if cat_key and confidence == "high":
                self._category_key = cat_key
                self._category_label = cat_label or cat_key
                self.session.category = CategoryInfo(
                    key=cat_key, label=self._category_label, source="auto"
                )
                await self._send(ev.category_identified(cat_key, self._category_label, confidence))

            if done_data.get("is_complete"):
                if not self._category_key:
                    # Need manual selection
                    cats = [{"key": c.key, "label": c.label} for c in self.categories]
                    await self._send(ev.category_manual_required(cats))
                    # Wait for category_selected message while keeping things going
                    cat = await self._wait_for_category_selection()
                    if cat:
                        self._category_key = cat["key"]
                        self._category_label = cat["label"]
                        self.session.category = CategoryInfo(
                            key=cat["key"], label=cat["label"], source="manual"
                        )
                        await self._send(ev.category_confirmed(cat["key"], cat["label"], "manual"))
                    else:
                        return  # dropped or stopped
                break

            # Speak next question (streamed text already collected in done_data)
            next_q = done_data.get("question_text", "")
            if next_q:
                self.session.qa_log.append(TicketQAEntry(
                    question_id=f"triage_q_{turn_idx + 2}",
                    question_text=next_q,
                    answer="",  # placeholder; filled on next iteration
                ))
                await self._speak_and_wait(next_q, turn=turn_idx + 1)

        # Transition to consultation
        self.session.phase = "consultation"
        await ticket_session_store.update(self.session)
        await self._send(ev.consultation_started(
            self._category_key or "general_medicine",
            self.session.turn_count,
        ))

    async def _stream_triage_turn(
        self, engine: TriageEngine, answer: str, turn_idx: int
    ) -> Optional[dict]:
        """Stream triage tokens, collect final __done__ dict."""
        question_tokens = ""
        done_data: Optional[dict] = None
        try:
            async for chunk in engine.next_turn_stream(
                self.session,
                answer,
                known_name=self._patient_name if self._patient_name != "the patient" else None,
                known_age=int(self._patient_age) if self._patient_age != "unknown" and self._patient_age.isdigit() else None,
                known_category=self._category_key,
                known_confidence="high" if self._category_key else "none",
            ):
                if self._stopped.is_set():
                    return None
                if isinstance(chunk, str):
                    question_tokens += chunk
                elif isinstance(chunk, dict) and chunk.get("__done__"):
                    done_data = chunk
        except Exception as exc:
            log.error("Triage stream failed: %s", exc)
            await self._send(ev.error("Something went wrong. Please try again."))
            return None
        return done_data

    # ── Consultation phase ─────────────────────────────────────

    async def _run_consultation(self) -> None:
        cat_label = self._category_label or (self._category_key or "General Medicine")
        engine = ConsultationEngine(
            category_label=cat_label,
            language=self.session.language,
            name=self._patient_name,
            age=self._patient_age,
            gender=self.session.gender,
        )

        # Extract the chief complaint from triage if it was mentioned
        # (usually the first patient answer in the triage conversation)
        known_complaint = None
        if self.session.qa_log and len(self.session.qa_log) > 0:
            known_complaint = self.session.qa_log[0].answer or None

        # Opening question for phase 2
        try:
            opening = await engine.opening_question(
                self._consult_covered,
                known_complaint=known_complaint,
            )
        except Exception as exc:
            log.error("Consultation opening failed: %s", exc)
            await self._send(ev.error("Could not start consultation phase."))
            return

        await self._speak_and_wait(opening, turn=self.session.turn_count)
        if self._stopped.is_set():
            return

        from app.ticketing.consultation_engine import MAX_CONSULTATION_TURNS

        for turn_idx in range(MAX_CONSULTATION_TURNS):
            if self._stopped.is_set():
                return

            answer = await self._collect_patient_answer()
            if answer is None:
                return

            current_q = opening if turn_idx == 0 else (
                self.session.qa_log[-1].question_text if self.session.qa_log else ""
            )
            self.session.qa_log.append(TicketQAEntry(
                question_id=f"consult_{turn_idx + 1}",
                question_text=current_q,
                answer=answer,
            ))
            self.session.turn_count += 1

            # Stream next consultation turn
            question_text = ""
            done_data: Optional[dict] = None
            try:
                async for chunk in engine.next_turn_stream(
                    self.session,
                    answer,
                    self._consult_covered,
                    known_complaint=known_complaint,
                ):
                    if self._stopped.is_set():
                        return
                    if isinstance(chunk, str):
                        question_text += chunk
                    elif isinstance(chunk, dict) and chunk.get("__done__"):
                        done_data = chunk
            except Exception as exc:
                log.error("Consultation stream failed: %s", exc)
                await self._send(ev.error("Something went wrong. Please try again."))
                return

            if done_data is None:
                return

            # Accumulate covered areas
            for area in (done_data.get("covered_areas") or []):
                if area not in self._consult_covered:
                    self._consult_covered.append(area)

            # Emit red flags
            for flag in (done_data.get("new_flags") or []):
                await self._send(ev.red_flag_raised(
                    flag.get("flag_type", "NOTE"),
                    flag.get("description", ""),
                ))

            # Save state
            await ticket_session_store.update(self.session)

            if done_data.get("is_complete"):
                break

            next_q = done_data.get("question_text", "")
            if next_q:
                await self._speak_and_wait(next_q, turn=self.session.turn_count)

        await self._send(ev.consultation_ended())
        self.session.phase = "result"
        await ticket_session_store.update(self.session)

    # ── Finalize (summary) ─────────────────────────────────────

    async def _finalize(self) -> None:
        transcript = "\n".join(
            f"Agent: {e.question_text}\nPatient: {e.answer}"
            for e in self.session.qa_log
            if e.answer
        )
        if not transcript.strip():
            self.session.status = "partial"
            await ticket_session_store.update(self.session)
            await self._send(ev.session_partial(self.session.session_id))
            return

        try:
            svc = SummarizationService()
            summary = await svc.summarize(transcript)
            self.session.summary = summary
        except Exception as exc:
            log.error("Summarization failed for ticket session %s: %s",
                      self.session.session_id, exc)
            self.session.summary = None

        self.session.status = "completed"
        from datetime import datetime
        self.session.ended_at = datetime.utcnow()
        await ticket_session_store.update(self.session)

        flags_json = [f.model_dump(mode="json") for f in self.session.flags]
        await self._send(ev.result_ready(self.session.summary, flags_json))

    # ── Audio / STT helpers ────────────────────────────────────

    async def _speak_and_wait(self, text: str, turn: int) -> None:
        """Synthesize TTS, send to client, then send agent_done_speaking to open mic."""
        if self._stopped.is_set():
            return
        try:
            mp3 = await synthesize_ticket(text, self.session.language)
            await self._send_audio(mp3, text, turn)
        except Exception as exc:
            log.warning("TTS failed, skipping audio: %s", exc)
            # Still send the question text so FE can display it
            await self._send({"type": "agent_speaking", "question": text, "turn": turn, "audio_b64": None})
        await self._send({"type": "agent_done_speaking", "turn": turn})
        self._mic_open = True

    async def _collect_patient_answer(self) -> Optional[str]:
        """
        Drain Deepgram events until UtteranceEnd fires, building the final transcript.
        Also drains the client WebSocket for control frames (stop, category_selected, ping).
        Returns the final transcript text, or None if the session was stopped.
        """
        self._utterance_buf.clear()
        self._mic_open = True
        final_text_parts: list[str] = []
        last_keepalive = time.monotonic()

        # Run two concurrent tasks: read from Deepgram, read client control frames
        answer_future: asyncio.Future[Optional[str]] = asyncio.get_event_loop().create_future()

        async def _dg_reader():
            assert self._dg is not None
            async for event in self._dg.events():
                if self._stopped.is_set() or answer_future.done():
                    return
                if event.type == DGEventType.PARTIAL:
                    await self._send(ev.partial_transcript(event.text))
                    if event.is_final:
                        final_text_parts.append(event.text)
                elif event.type == DGEventType.UTTERANCE_END:
                    full_text = " ".join(final_text_parts).strip()
                    if not answer_future.done():
                        answer_future.set_result(full_text or None)
                    return
                elif event.type == DGEventType.ERROR:
                    if not answer_future.done():
                        answer_future.set_exception(RuntimeError(event.text))
                    return

        async def _client_reader():
            while not self._stopped.is_set() and not answer_future.done():
                try:
                    msg = await asyncio.wait_for(self.ws.receive(), timeout=1.0)
                except asyncio.TimeoutError:
                    # Send keepalive to Deepgram
                    nonlocal last_keepalive
                    if time.monotonic() - last_keepalive > _KEEPALIVE_INTERVAL:
                        last_keepalive = time.monotonic()
                        if self._dg:
                            await self._dg.keepalive()
                    continue
                except WebSocketDisconnect:
                    self._stopped.set()
                    if not answer_future.done():
                        answer_future.set_result(None)
                    return

                if msg.get("bytes") and self._mic_open:
                    frame = msg["bytes"]
                    if len(frame) <= _MAX_AUDIO_FRAME_BYTES and self._dg:
                        await self._dg.send_audio(frame)

                elif msg.get("text"):
                    try:
                        data = json.loads(msg["text"])
                    except Exception:
                        continue
                    mtype = data.get("type")
                    if mtype == "stop":
                        self._stopped.set()
                        if not answer_future.done():
                            answer_future.set_result(None)
                        return
                    elif mtype == "ping":
                        await self._send({"type": "pong"})
                    elif mtype == "category_selected":
                        # Store for pickup by _wait_for_category_selection
                        self._pending_category = data

        dg_task = asyncio.create_task(_dg_reader())
        client_task = asyncio.create_task(_client_reader())

        try:
            result = await answer_future
        except Exception as exc:
            log.error("Patient answer collection failed: %s", exc)
            result = None
        finally:
            dg_task.cancel()
            client_task.cancel()
            await asyncio.gather(dg_task, client_task, return_exceptions=True)

        self._mic_open = False
        # Tell Deepgram we're done for this turn
        if self._dg:
            await self._dg.finalize()

        return result

    async def _wait_for_category_selection(self) -> Optional[dict]:
        """Wait for a category_selected control frame from the client."""
        self._pending_category = None  # type: ignore[attr-defined]
        deadline = time.monotonic() + 120.0  # 2 min for user to pick
        while time.monotonic() < deadline and not self._stopped.is_set():
            # Check if already set by _client_reader
            if hasattr(self, "_pending_category") and self._pending_category:
                cat = self._pending_category
                self._pending_category = None  # type: ignore[attr-defined]
                return {"key": cat.get("key", ""), "label": cat.get("label", cat.get("key", ""))}
            try:
                msg = await asyncio.wait_for(self.ws.receive(), timeout=1.0)
            except asyncio.TimeoutError:
                continue
            except WebSocketDisconnect:
                self._stopped.set()
                return None
            if msg.get("text"):
                try:
                    data = json.loads(msg["text"])
                except Exception:
                    continue
                if data.get("type") == "category_selected":
                    return {"key": data.get("key", ""), "label": data.get("label", data.get("key", ""))}
                elif data.get("type") == "stop":
                    self._stopped.set()
                    return None
        return None

    # ── Teardown ───────────────────────────────────────────────

    async def _teardown(self) -> None:
        if self._dg:
            await self._dg.close()
        if self.session.status == "active":
            self.session.status = "partial"
            await ticket_session_store.update(self.session)
            await self._send(ev.session_partial(self.session.session_id))
        await self._send({"type": "ended", "session_id": self.session.session_id})
