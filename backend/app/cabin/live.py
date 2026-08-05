"""CabinLiveSession — the orchestrator for one active cabin WebSocket.

Four concurrent responsibilities, each its own asyncio task, joined with
FIRST_COMPLETED so any one exiting tears the rest down:
  _recv_client   — reads the doctor's browser socket (audio + control frames)
  _pump_to_scribe — drains the audio queue into the ElevenLabs socket
  _recv_scribe   — reads ElevenLabs events, builds utterances, drives analysis
  _analysis_loop — debounced role attribution + gated panel/suggestions + persistence flush

Partials never touch the LLM — only committed utterances do. Audio bytes are
collected in memory (small: ~38MB for a 20-minute PCM16/16kHz consult, same
pattern the existing voice_stream handler already uses) and uploaded to R2 as
a WAV file when the session ends.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import tempfile
import time
import uuid
import wave
from datetime import datetime
from typing import Any, Optional

from fastapi import WebSocket, WebSocketDisconnect

from app.agent import usage
from app.cabin import leases
from app.cabin.analysis import (
    attribute_roles,
    extract_panel_delta,
    merge_panel_delta,
    panel_clinically_changed,
    reconcile_panel,
    suggest,
)
from app.cabin.gaps import detect_gaps, gap_key
from app.cabin.models import (
    CabinSession,
    ClinicalPanel,
    SessionCost,
    Utterance,
    UtteranceRole,
)
from app.cabin.postprocess import rediarize
from app.cabin.scribe import ScribeErrorClass, ScribeStream
from app.cabin.store import cabin_session_store
from app.clinical import patient_store
from app.clinical.profile import PatientProfile, build_profile
from app.core.config import settings
from app.storage import r2

log = logging.getLogger(__name__)

GENERIC_STT_ERROR = "Transcription is temporarily unavailable. Please try again."
GENERIC_ANALYSIS_ERROR = (
    "Something went wrong generating suggestions. The transcript is unaffected."
)

_MAX_CLIENT_FRAME_BYTES = 32 * 1024
_WARNING_THROTTLE_SECS = 10.0
_ERROR_THROTTLE_SECS = 60.0
_SPOOL_BLOCK_BYTES = 1024 * 1024  # spool -> WAV copy block; bounds peak memory

# asyncio only holds weak references to running tasks, so a fire-and-forget
# create_task() can be garbage-collected mid-flight. Anything spawned to outlive the
# request (the re-diarization pass, planned socket cutovers) is parked here until done.
_background_tasks: set[asyncio.Task] = set()


def _spawn(coro) -> asyncio.Task:
    task = asyncio.create_task(coro)
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)
    return task


class CabinLiveSession:
    def __init__(self, session: CabinSession, websocket: WebSocket) -> None:
        self.session = session
        self.ws = websocket
        self.utterances: list[Utterance] = list(session.utterances)
        self.panel = session.panel
        self.suggestions = session.suggestions
        self._seq = 0
        # Audio is spooled to a temp file rather than accumulated in memory: a 90-minute
        # consult is ~170MB of PCM, and the old list-of-frames also peaked at ~3x that
        # while being joined and WAV-wrapped at teardown.
        self._spool: Optional[Any] = None
        self._spool_failed = False
        self._pcm_bytes = 0
        self._usage_calls: list[usage.Call] = []
        # Patient history to check the consultation against. Loaded once in run();
        # None means "not loaded or no patient", which disables gap detection.
        self._profile: Optional[PatientProfile] = None
        self._profile_loaded = False
        self._gaps_sent: set[str] = set()
        self._last_gap_run = 0.0
        self._gap_passes = 0
        self._audio_q: asyncio.Queue[bytes] = asyncio.Queue(
            maxsize=settings.CABIN_AUDIO_QUEUE_MAX
        )
        self._scribe: Optional[ScribeStream] = None
        self._stopped = asyncio.Event()
        self._dirty = False
        self._pending_words = 0
        self._new_utterance = False
        # How far into self.utterances the panel has already been extracted. Each pass
        # only sends what is past this mark, which is what keeps the call cost flat
        # regardless of how long the consultation runs.
        self._extracted_upto = len(self.utterances)
        self._panel_passes = 0
        self._last_warning_at: dict[str, float] = {}
        self._last_error_at = 0.0
        self._connect_started_at = 0.0
        self._session_started_at = 0.0
        self._end_reason = "ended"

    # ── outbound wire helpers ──────────────────────────────────

    async def _send(self, payload: dict[str, Any]) -> None:
        payload.setdefault("ts", time.time())
        try:
            await asyncio.wait_for(self.ws.send_json(payload), timeout=5.0)
        except Exception:
            self._stopped.set()

    async def _warn(self, code: str, message: str = "") -> None:
        now = time.monotonic()
        if now - self._last_warning_at.get(code, 0.0) < _WARNING_THROTTLE_SECS:
            return
        self._last_warning_at[code] = now
        await self._send({"type": "stt_warning", "code": code, "message": message})

    async def _error(self, message: str, fatal: bool = False) -> None:
        """Non-fatal errors are throttled — an LLM outage would otherwise emit one per
        analysis pass. Fatal errors always go out; the session is ending anyway."""
        if not fatal:
            now = time.monotonic()
            if now - self._last_error_at < _ERROR_THROTTLE_SECS:
                return
            self._last_error_at = now
        await self._send({"type": "error", "fatal": fatal, "message": message})

    def _next_seq(self) -> int:
        self._seq += 1
        return self._seq

    # ── lifecycle ───────────────────────────────────────────────

    async def send_snapshot(self) -> None:
        if not self.utterances and self.panel is None and self.suggestions is None:
            return
        await self._send(
            {
                "type": "snapshot",
                "utterances": [u.model_dump(mode="json") for u in self.utterances],
                "panel": self.panel.model_dump(mode="json") if self.panel else None,
                "suggestions": (
                    self.suggestions.model_dump(mode="json")
                    if self.suggestions
                    else None
                ),
            }
        )

    async def run(self) -> None:
        # Bound here, before any create_task below: a child task inherits a copy of the
        # context at creation time, and the bound list is shared by reference, so calls
        # made by the four worker tasks land in this session's totals and no other's.
        usage.bind(self._usage_calls)
        if self.session.consent_captured_at is None:
            await self._send(
                {
                    "type": "error",
                    "fatal": True,
                    "message": "Consent not recorded for this session.",
                }
            )
            return

        try:
            start_msg = await asyncio.wait_for(self.ws.receive(), timeout=10.0)
        except (asyncio.TimeoutError, WebSocketDisconnect):
            return
        secondary_languages = [
            code.strip()
            for code in settings.CABIN_STT_SECONDARY_LANGUAGES.split(",")
            if code.strip()
        ]
        keyterms: list[str] = []
        language_code: Optional[str] = None
        if start_msg.get("text"):
            try:
                data = json.loads(start_msg["text"])
                secondary_languages = (
                    data.get("secondary_languages") or secondary_languages
                )
                keyterms = (data.get("keyterms") or [])[:50]
                language_code = data.get("language_code")
            except (TypeError, ValueError):
                pass

        self._scribe = ScribeStream(
            secondary_languages=secondary_languages,
            keyterms=keyterms,
            language_code=language_code,
        )
        try:
            await self._scribe.connect()
        except Exception as exc:
            log.error(
                "Scribe connect failed for cabin session %s: %s",
                self.session.session_id,
                exc,
                exc_info=True,
            )
            await self._send(
                {"type": "error", "fatal": True, "message": GENERIC_STT_ERROR}
            )
            return
        self._connect_started_at = time.monotonic()
        self._session_started_at = self._connect_started_at

        await self.send_snapshot()
        await self._send(
            {"type": "ready", "session_id": self.session.session_id, "stt": "connected"}
        )

        tasks = [
            asyncio.create_task(self._recv_client()),
            asyncio.create_task(self._pump_to_scribe()),
            asyncio.create_task(self._recv_scribe()),
            asyncio.create_task(self._analysis_loop()),
        ]
        try:
            done, pending = await asyncio.wait(
                tasks, return_when=asyncio.FIRST_COMPLETED
            )
            for task in done:
                exc = task.exception()
                if exc:
                    log.error(
                        "Cabin task failed for session %s: %s",
                        self.session.session_id,
                        exc,
                        exc_info=exc,
                    )
        finally:
            self._stopped.set()
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            await self._teardown()

    async def _teardown(self) -> None:
        if self._scribe is not None:
            await self._scribe.close()
        if self.session.status == "active":
            self.session.status = self._end_reason
            self.session.ended_at = datetime.utcnow()
        await self._final_reconcile()
        # After the last LLM call, so the reconciliation's own spend is counted, and
        # before the flush that persists it.
        self._record_cost()
        await self._flush(force=True)
        if settings.CABIN_ARCHIVE_AUDIO and self._pcm_bytes:
            try:
                await self._archive_audio()
                await self._flush(force=True)
            except Exception as exc:
                log.warning(
                    "Audio archival failed for session %s: %s",
                    self.session.session_id,
                    exc,
                )
            else:
                if settings.CABIN_REDIARIZE_ON_END:
                    # Runs after this handler returns and closes the socket — the doctor
                    # doesn't wait on it, and a failure here is non-fatal (see postprocess.py).
                    _spawn(rediarize(self.session.session_id))
        self._close_spool()
        await self._send(
            {
                "type": "ended",
                "session_id": self.session.session_id,
                "utterance_count": len(self.utterances),
            }
        )

    def _close_spool(self) -> None:
        """NamedTemporaryFile deletes on close."""
        if self._spool is None:
            return
        try:
            self._spool.close()
        except Exception:
            pass
        self._spool = None

    def _record_cost(self) -> None:
        totals = usage.summarize(self._usage_calls)
        self.session.cost = SessionCost(
            calls=totals.calls,
            input_tokens=totals.input_tokens,
            output_tokens=totals.output_tokens,
            usd=round(totals.usd, 6),
            inr=round(usage.inr(totals.usd), 4),
        )
        self._dirty = True
        duration = (
            time.monotonic() - self._session_started_at
            if self._session_started_at
            else 0.0
        )
        log.info(
            "cabin_cost session_id=%s doctor_id=%s status=%s duration_s=%.0f "
            "utterances=%d llm_calls=%d input_tokens=%d output_tokens=%d "
            "usd=%.4f inr=%.2f",
            self.session.session_id,
            self.session.doctor_id,
            self.session.status,
            duration,
            len(self.utterances),
            totals.calls,
            totals.input_tokens,
            totals.output_tokens,
            totals.usd,
            usage.inr(totals.usd),
        )

    async def _final_reconcile(self) -> None:
        """One last full pass over the transcript before the record is persisted.

        The live panel is an accumulation of increments and may carry a value the
        patient later corrected. This is the version that goes downstream to coding and
        insurance, so it has to reflect the whole conversation. Best-effort: if it
        fails, the incremental panel stands rather than the session losing its panel.
        """
        if not self.utterances:
            return
        try:
            self.panel = await reconcile_panel(self.utterances, self.panel)
            self._dirty = True
        except Exception as exc:
            log.warning(
                "Final panel reconciliation failed for session %s, keeping incremental panel: %s",
                self.session.session_id,
                exc,
            )

    def _write_spool(self, frame: bytes) -> None:
        """Tee one frame to the on-disk spool. Best-effort: if the spool cannot be
        written the consultation continues without a recording, because losing the
        archive must never take the live transcript down with it."""
        if self._spool_failed:
            return
        try:
            if self._spool is None:
                self._spool = tempfile.NamedTemporaryFile(
                    prefix=f"cabin-{self.session.session_id}-", suffix=".pcm"
                )
            self._spool.write(frame)
            self._pcm_bytes += len(frame)
        except Exception as exc:
            self._spool_failed = True
            log.warning(
                "Audio spool unavailable for session %s, continuing without a "
                "recording: %s",
                self.session.session_id,
                exc,
            )
            _spawn(self._warn("archive_unavailable"))

    async def _archive_audio(self) -> None:
        """Stream the spooled PCM into a WAV and upload it. The WAV is built by reading
        the spool in fixed-size blocks, so neither the raw audio nor the wrapped file is
        ever held whole in memory."""
        assert self._spool is not None
        self._spool.flush()
        self._spool.seek(0)
        wav = tempfile.NamedTemporaryFile(
            prefix=f"cabin-{self.session.session_id}-", suffix=".wav", delete=False
        )
        try:
            with wave.open(wav, "wb") as wav_file:
                wav_file.setnchannels(1)
                wav_file.setsampwidth(2)  # PCM16
                wav_file.setframerate(16000)
                while True:
                    block = self._spool.read(_SPOOL_BLOCK_BYTES)
                    if not block:
                        break
                    wav_file.writeframes(block)
            wav.close()
            key = await r2.upload_audio_file(
                wav.name, self.session.session_id, mime_type="audio/wav"
            )
            self.session.audio_key = key
            self._dirty = True
        finally:
            try:
                wav.close()
            except Exception:
                pass
            try:
                os.remove(wav.name)
            except OSError:
                pass

    # ── receive from the doctor's browser ───────────────────────

    async def _recv_client(self) -> None:
        while not self._stopped.is_set():
            try:
                msg = await asyncio.wait_for(self.ws.receive(), timeout=180.0)
            except asyncio.TimeoutError:
                continue
            except WebSocketDisconnect:
                self._end_reason = "interrupted"
                return

            if msg.get("type") == "websocket.disconnect":
                self._end_reason = "interrupted"
                return

            if msg.get("bytes") is not None:
                frame = msg["bytes"]
                if len(frame) > _MAX_CLIENT_FRAME_BYTES:
                    await self._warn("chunk_too_large")
                    continue
                self._write_spool(frame)
                try:
                    self._audio_q.put_nowait(frame)
                except asyncio.QueueFull:
                    try:
                        self._audio_q.get_nowait()
                    except asyncio.QueueEmpty:
                        pass
                    self._audio_q.put_nowait(frame)
                    await self._warn(
                        "audio_backlog",
                        "Falling behind on audio; oldest frames are being dropped.",
                    )
                continue

            if msg.get("text") is None:
                continue
            try:
                data = json.loads(msg["text"])
            except (TypeError, ValueError):
                continue
            mtype = data.get("type")
            if mtype == "stop":
                self._end_reason = "ended"
                return
            if mtype == "note":
                text = (data.get("text") or "").strip()
                if text:
                    self._append_utterance(
                        text, role=UtteranceRole.DOCTOR, role_confidence=1.0
                    )
            elif mtype == "ping":
                await self._send({"type": "pong"})

    async def _pump_to_scribe(self) -> None:
        assert self._scribe is not None
        while not self._stopped.is_set():
            try:
                frame = await asyncio.wait_for(self._audio_q.get(), timeout=1.0)
            except asyncio.TimeoutError:
                continue
            try:
                await self._scribe.send_audio(frame)
            except Exception as exc:
                log.warning(
                    "send_audio failed for session %s: %s", self.session.session_id, exc
                )

    # ── receive from ElevenLabs ──────────────────────────────────

    def _append_utterance(
        self,
        text: str,
        role: UtteranceRole = UtteranceRole.UNKNOWN,
        role_confidence: float = 0.0,
        language: Optional[str] = None,
        speaker_id: Optional[str] = None,
        started_at: Optional[float] = None,
        ended_at: Optional[float] = None,
    ) -> Utterance:
        utterance = Utterance(
            utterance_id=uuid.uuid4().hex,
            seq=len(self.utterances),
            text=text,
            role=role,
            role_confidence=role_confidence,
            language=language,
            speaker_id=speaker_id,
            started_at=started_at,
            ended_at=ended_at,
        )
        self.utterances.append(utterance)
        self._pending_words += len(text.split())
        self._new_utterance = True
        self._dirty = True
        return utterance

    async def _recv_scribe(self) -> None:
        assert self._scribe is not None
        async for event in self._scribe.events():
            if self._stopped.is_set():
                return

            if event.error_class is not None:
                if (
                    event.error_class == ScribeErrorClass.FATAL
                    or event.type == "fatal_disconnect"
                ):
                    log.error(
                        "Scribe fatal event for session %s: %s",
                        self.session.session_id,
                        event.type,
                    )
                    await self._send(
                        {"type": "error", "fatal": True, "message": GENERIC_STT_ERROR}
                    )
                    self._stopped.set()
                    return
                if event.type == "reconnecting":
                    await self._warn(
                        "reconnecting", "Reconnecting to transcription service."
                    )
                elif event.error_class == ScribeErrorClass.TRANSIENT:
                    await self._warn(
                        event.type, "Transcription service is temporarily throttled."
                    )
                elif event.error_class == ScribeErrorClass.INFORMATIONAL:
                    await self._warn("no_speech", "No speech detected.")
                elif event.error_class == ScribeErrorClass.OUR_BUG:
                    log.error(
                        "Scribe reported %s for session %s: %s",
                        event.type,
                        self.session.session_id,
                        event.data,
                    )
                continue

            if event.type == "partial_transcript":
                text = event.data.get("text", "")
                if text:
                    await self._send({"type": "partial", "text": text})
                continue

            if event.type in (
                "committed_transcript_with_timestamps",
                "committed_transcript",
            ):
                text = (event.data.get("text") or "").strip()
                if not text:
                    continue
                language = event.data.get("language_code")
                speaker_id = event.data.get("speaker_id")
                # Word-level timestamp schema is not fully documented by ElevenLabs (see
                # plan Step 0) — read defensively and leave None if the shape doesn't match.
                words = event.data.get("words") or []
                started_at = words[0].get("start") if words else event.data.get("start")
                ended_at = words[-1].get("end") if words else event.data.get("end")
                utterance = self._append_utterance(
                    text,
                    language=language,
                    speaker_id=speaker_id,
                    started_at=started_at,
                    ended_at=ended_at,
                )
                await self._send(
                    {
                        "type": "utterance",
                        "utterance": utterance.model_dump(mode="json"),
                    }
                )

    # ── analysis cadence ──────────────────────────────────────────

    async def _analysis_loop(self) -> None:
        last_role_run = 0.0
        last_panel_run = 0.0
        last_flush = time.monotonic()
        last_lease_renew = time.monotonic()

        while not self._stopped.is_set():
            await asyncio.sleep(0.5)
            now = time.monotonic()

            if (
                now - self._session_started_at
            ) >= settings.CABIN_MAX_SESSION_MINUTES * 60:
                log.info(
                    "Cabin session %s hit the %d-minute cap, closing cleanly",
                    self.session.session_id,
                    settings.CABIN_MAX_SESSION_MINUTES,
                )
                self._end_reason = "ended"
                self._stopped.set()
                return

            if (
                self._scribe is not None
                and (now - self._connect_started_at)
                >= settings.CABIN_STT_ROLLING_RECONNECT_SECS
            ):
                self._connect_started_at = now
                _spawn(self._scribe.rolling_reconnect())

            if (
                self._new_utterance
                and (now - last_role_run) >= settings.CABIN_ROLE_DEBOUNCE_SECS
            ):
                self._new_utterance = False
                last_role_run = now
                await self._run_role_attribution()

            if (
                (now - last_panel_run) >= settings.CABIN_PANEL_MIN_INTERVAL_SECS
                and self._pending_words >= settings.CABIN_MIN_NEW_WORDS_FOR_ANALYSIS
            ):
                last_panel_run = now
                self._pending_words = 0
                await self._run_panel_and_maybe_suggest()

            if (
                self._dirty
                and (now - last_flush) >= settings.CABIN_PERSIST_INTERVAL_SECS
            ):
                await self._flush()
                last_flush = now

            # Renewed here rather than in a fifth task: this loop is already the
            # session's heartbeat and already ends when _stopped is set. A failed
            # renewal is logged and ignored — ending a live consultation over a lost
            # lease would destroy clinical data, which is worse than the duplicate
            # connection it would prevent.
            if (now - last_lease_renew) >= settings.CABIN_LEASE_RENEW_SECS:
                last_lease_renew = now
                await leases.renew(self.session.session_id)

    async def _run_role_attribution(self) -> None:
        try:
            attribution = await attribute_roles(self.utterances)
        except Exception as exc:
            log.error(
                "attribute_roles failed for session %s: %s",
                self.session.session_id,
                exc,
                exc_info=True,
            )
            await self._error(GENERIC_ANALYSIS_ERROR)
            return
        by_id = {u.utterance_id: u for u in self.utterances}
        for label in attribution.labels:
            utterance = by_id.get(label.utterance_id)
            if utterance is None:
                continue
            utterance.role = label.role
            utterance.role_confidence = label.confidence
            await self._send(
                {
                    "type": "utterance_role",
                    "utterance_id": label.utterance_id,
                    "role": label.role.value,
                    "confidence": label.confidence,
                }
            )
        self._dirty = True

    async def _load_profile(self) -> None:
        """Fetch the patient's history once, lazily.

        Deliberately not done in run(): that would put two Mongo reads on the connect
        path before the doctor sees `ready`, to serve a check that cannot fire for at
        least CABIN_GAP_MIN_INTERVAL_SECS anyway.

        Best-effort — no patient linked, or an unreachable store, simply means no gap
        alerts, and it must never stop a consultation from starting. Loaded at most once
        either way: a failure leaves an empty profile that disables the feature for the
        rest of the session rather than retrying every pass.
        """
        self._profile_loaded = True
        self._profile = PatientProfile()
        if not self.session.patient_id:
            return
        try:
            patient = await patient_store.get(
                self.session.patient_id, self.session.doctor_id
            )
            prior = await cabin_session_store.list_for_patient(
                self.session.patient_id, self.session.doctor_id
            )
            prior = [p for p in prior if p.get("session_id") != self.session.session_id]
            self._profile = build_profile(patient, prior)
        except Exception as exc:
            log.warning(
                "Patient profile unavailable for session %s, gap alerts disabled: %s",
                self.session.session_id,
                exc,
            )

    async def _maybe_emit_gaps(self, panel_changed: bool) -> None:
        """Check the consultation against the patient's known history.

        Three gates, cheapest first: no profile at all (a first-time patient, and the
        common case) costs nothing; then the same clinical-change signal that gates the
        expensive suggest call; then a minimum interval of its own, because gaps move far
        more slowly than the panel does.

        Best-effort throughout — a failure here must leave the transcript and panel
        exactly as they were, like every other analysis call.
        """
        # Cheapest gates first. A walk-in with no patient record costs nothing at all,
        # which is also the common case.
        if not self.session.patient_id:
            return
        if not panel_changed:
            return
        if self._gap_passes >= settings.CABIN_GAP_MAX_PASSES:
            return
        now = time.monotonic()
        if (now - self._last_gap_run) < settings.CABIN_GAP_MIN_INTERVAL_SECS:
            return

        if not self._profile_loaded:
            await self._load_profile()
        if self._profile is None or self._profile.is_empty():
            return

        self._last_gap_run = now
        self._gap_passes += 1

        try:
            alerts = await detect_gaps(self._profile, self.panel or ClinicalPanel())
        except Exception as exc:
            log.error(
                "gap detection failed for session %s: %s",
                self.session.session_id,
                exc,
                exc_info=True,
            )
            return  # deliberately silent: a missing alert is not worth alarming the doctor

        fresh = [g for g in alerts.gaps if gap_key(g) not in self._gaps_sent]
        if not fresh:
            return
        self._gaps_sent.update(gap_key(g) for g in fresh)
        await self._send(
            {
                "type": "gap_alert",
                "seq": self._next_seq(),
                "gaps": [g.model_dump(mode="json") for g in fresh],
            }
        )

    async def _run_panel_and_maybe_suggest(self) -> None:
        pending = self.utterances[self._extracted_upto :]
        if not pending:
            return
        # Snapshot the mark before the await: more utterances can land while the call
        # is in flight, and they belong to the next pass, not this one.
        upto = len(self.utterances)
        self._panel_passes += 1
        reconciling = (
            self._panel_passes % settings.CABIN_PANEL_RECONCILE_EVERY_N_PASSES == 0
        )

        try:
            if reconciling:
                # Periodic full pass: catches self-corrections, retractions, and
                # anything the incremental deltas missed. A delta can only ever add.
                new_panel = await reconcile_panel(self.utterances, self.panel)
                should_suggest = panel_clinically_changed(self.panel, new_panel)
            else:
                delta = await extract_panel_delta(pending, self.panel)
                should_suggest = delta.has_clinical_change()
                new_panel = merge_panel_delta(self.panel, delta)
        except Exception as exc:
            log.error(
                "panel %s failed for session %s: %s",
                "reconciliation" if reconciling else "delta extraction",
                self.session.session_id,
                exc,
                exc_info=True,
            )
            # Leave the cursor untouched so this stretch of speech is retried rather
            # than silently dropped from the panel.
            await self._error(GENERIC_ANALYSIS_ERROR)
            return

        self._extracted_upto = upto
        self.panel = new_panel
        self._dirty = True
        await self._send(
            {
                "type": "panel",
                "seq": self._next_seq(),
                "panel": new_panel.model_dump(mode="json"),
            }
        )

        await self._maybe_emit_gaps(should_suggest)

        if not should_suggest:
            return
        try:
            new_suggestions = await suggest(
                new_panel,
                self.utterances[-settings.CABIN_SUGGEST_CONTEXT_UTTERANCES :],
            )
        except Exception as exc:
            log.error(
                "suggest failed for session %s: %s",
                self.session.session_id,
                exc,
                exc_info=True,
            )
            await self._error(GENERIC_ANALYSIS_ERROR)
            return
        self.suggestions = new_suggestions
        self._dirty = True
        await self._send(
            {
                "type": "suggestions",
                "seq": self._seq,
                "suggestions": new_suggestions.model_dump(mode="json"),
            }
        )

    # ── persistence ────────────────────────────────────────────────

    async def _flush(self, force: bool = False) -> None:
        if not (self._dirty or force):
            return
        self.session.utterances = self.utterances
        self.session.panel = self.panel
        self.session.suggestions = self.suggestions
        await cabin_session_store.update(self.session)
        self._dirty = False
