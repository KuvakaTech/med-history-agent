"""CabinLiveSession tests — the orchestrator's control-flow and safety properties.

Covers the things that are painful to verify against a live consultation: the consent
gate, audio backpressure, the Sonnet cost gate, error throttling, and the session cap.
"""

from __future__ import annotations

import asyncio
import io
import time
import wave
from datetime import datetime
from unittest.mock import AsyncMock, patch

import pytest

from app.agent import usage
from app.cabin.live import CabinLiveSession
from app.cabin.models import (
    CabinSession,
    ClinicalPanel,
    LiveSuggestions,
    PanelDelta,
    ReportedSymptom,
    RoleAttribution,
    RoleLabel,
    UtteranceRole,
)
from app.clinical.context import Specialty
from app.core.config import settings


class FakeWebSocket:
    """Stand-in for Starlette's WebSocket: receive() yields ASGI-shaped dicts."""

    def __init__(self, incoming: list[dict] | None = None):
        self._incoming = list(incoming or [])
        self.sent: list[dict] = []

    async def receive(self) -> dict:
        if self._incoming:
            return self._incoming.pop(0)
        return {"type": "websocket.disconnect"}

    async def send_json(self, payload: dict) -> None:
        self.sent.append(payload)


def make_session(consent: bool = True) -> CabinSession:
    return CabinSession(
        session_id="sess-1",
        doctor_id="doc-1",
        specialty=Specialty.GENERAL_MEDICINE,
        consent_captured_at=datetime.utcnow() if consent else None,
    )


def make_live(session: CabinSession | None = None, incoming: list[dict] | None = None):
    ws = FakeWebSocket(incoming)
    return CabinLiveSession(session or make_session(), ws), ws


def types_of(ws: FakeWebSocket) -> list[str]:
    return [m["type"] for m in ws.sent]


def spooled(live) -> bytes:
    """Everything written to the on-disk audio spool so far. Audio is streamed to a
    temp file rather than held in memory, so this is the archive's observation point."""
    if live._spool is None:
        return b""
    live._spool.flush()
    pos = live._spool.tell()
    live._spool.seek(0)
    try:
        return live._spool.read()
    finally:
        live._spool.seek(pos)


# ── consent gate ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_run_refuses_session_without_consent():
    """DPDP Act 2023: no audio may be captured before consent is recorded. The socket
    must refuse before it ever opens an ElevenLabs connection."""
    live, ws = make_live(make_session(consent=False))

    with patch("app.cabin.live.ScribeStream") as scribe_cls:
        await live.run()

    assert scribe_cls.call_count == 0, "connected to STT despite missing consent"
    assert ws.sent[0]["type"] == "error"
    assert ws.sent[0]["fatal"] is True


# ── client frame handling ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_note_becomes_a_doctor_utterance():
    live, _ws = make_live(
        incoming=[
            {"text": '{"type": "note", "text": "BP 150/95 on exam"}'},
            {"text": '{"type": "stop"}'},
        ]
    )
    await live._recv_client()

    assert len(live.utterances) == 1
    assert live.utterances[0].text == "BP 150/95 on exam"
    assert live.utterances[0].role == UtteranceRole.DOCTOR
    assert live.utterances[0].role_confidence == 1.0, "a typed note is not a guess"


@pytest.mark.asyncio
async def test_empty_note_is_ignored():
    live, _ws = make_live(
        incoming=[
            {"text": '{"type": "note", "text": "   "}'},
            {"text": '{"type": "stop"}'},
        ]
    )
    await live._recv_client()
    assert live.utterances == []


@pytest.mark.asyncio
async def test_ping_gets_pong():
    live, ws = make_live(
        incoming=[{"text": '{"type": "ping"}'}, {"text": '{"type": "stop"}'}]
    )
    await live._recv_client()
    assert "pong" in types_of(ws)


@pytest.mark.asyncio
async def test_stop_ends_cleanly_disconnect_marks_interrupted():
    live, _ = make_live(incoming=[{"text": '{"type": "stop"}'}])
    await live._recv_client()
    assert live._end_reason == "ended"

    live2, _ = make_live(incoming=[{"type": "websocket.disconnect"}])
    await live2._recv_client()
    assert live2._end_reason == "interrupted"


@pytest.mark.asyncio
async def test_malformed_control_frame_does_not_kill_the_session():
    live, _ = make_live(
        incoming=[
            {"text": "not json at all"},
            {"text": '{"type": "note", "text": "ok"}'},
            {"text": '{"type": "stop"}'},
        ]
    )
    await live._recv_client()
    assert len(live.utterances) == 1


@pytest.mark.asyncio
async def test_oversized_frame_is_rejected_not_queued():
    live, ws = make_live(
        incoming=[{"bytes": b"\x00" * (33 * 1024)}, {"text": '{"type": "stop"}'}]
    )
    await live._recv_client()

    assert live._audio_q.qsize() == 0
    assert spooled(live) == b""
    assert "stt_warning" in types_of(ws)


# ── backpressure ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_backpressure_drops_oldest_frame_but_archives_every_frame(monkeypatch):
    """Stale audio is worthless to a live transcript, so the queue drops the oldest
    frame under pressure. The archive must still receive every frame — it is teed on
    receipt, before the queue — or the recording would have gaps the doctor never sees.
    """
    monkeypatch.setattr(settings, "CABIN_AUDIO_QUEUE_MAX", 3)
    frames = [{"bytes": bytes([i]) * 10} for i in range(6)]
    live, ws = make_live(incoming=frames + [{"text": '{"type": "stop"}'}])

    await live._recv_client()

    assert live._audio_q.qsize() == 3, "queue must stay bounded"
    assert spooled(live) == b"".join(
        bytes([i]) * 10 for i in range(6)
    ), "archive lost frames that the queue dropped"
    assert "stt_warning" in types_of(ws)

    queued = [live._audio_q.get_nowait() for _ in range(3)]
    assert queued == [
        bytes([3]) * 10,
        bytes([4]) * 10,
        bytes([5]) * 10,
    ], "kept the stale frames instead of the fresh ones"


@pytest.mark.asyncio
async def test_warning_is_throttled():
    live, ws = make_live()
    await live._warn("audio_backlog", "first")
    await live._warn("audio_backlog", "second")
    assert types_of(ws).count("stt_warning") == 1


@pytest.mark.asyncio
async def test_non_fatal_errors_are_throttled_fatal_always_sent():
    """An LLM outage must not emit one error per analysis pass."""
    live, ws = make_live()
    await live._error("analysis blew up")
    await live._error("analysis blew up again")
    assert types_of(ws).count("error") == 1

    await live._error("terminal", fatal=True)
    errors = [m for m in ws.sent if m["type"] == "error"]
    assert errors[-1]["fatal"] is True


# ── the Sonnet cost gate ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_suggest_is_skipped_when_the_delta_adds_nothing_clinical():
    """This gate is the difference between paying for Sonnet every 8 seconds and
    paying for it only when the consultation actually moved."""
    live, ws = make_live()
    live._append_utterance("some chatter")

    with (
        patch(
            "app.cabin.live.extract_panel_delta",
            new=AsyncMock(return_value=PanelDelta()),
        ),
        patch("app.cabin.live.suggest", new=AsyncMock()) as mock_suggest,
    ):
        await live._run_panel_and_maybe_suggest()

    mock_suggest.assert_not_awaited()
    assert "panel" in types_of(ws)
    assert "suggestions" not in types_of(ws)


@pytest.mark.asyncio
async def test_suggest_runs_when_the_delta_brings_new_clinical_content():
    live, ws = make_live()
    live._append_utterance("mujhe khaansi hai")
    delta = PanelDelta(new_symptoms=[ReportedSymptom(name="cough")])

    with (
        patch("app.cabin.live.extract_panel_delta", new=AsyncMock(return_value=delta)),
        patch(
            "app.cabin.live.suggest", new=AsyncMock(return_value=LiveSuggestions())
        ) as mock_suggest,
    ):
        await live._run_panel_and_maybe_suggest()

    mock_suggest.assert_awaited_once()
    assert "suggestions" in types_of(ws)
    assert [s.name for s in live.panel.symptoms] == ["cough"]


@pytest.mark.asyncio
async def test_each_pass_only_extracts_utterances_it_has_not_seen():
    """The cursor is what keeps per-pass cost flat — without it every pass would
    re-send the entire consultation."""
    live, _ = make_live()
    live._append_utterance("first")

    seen: list[list[str]] = []

    async def capture(new_utterances, _panel):
        seen.append([u.text for u in new_utterances])
        return PanelDelta()

    with patch("app.cabin.live.extract_panel_delta", new=capture):
        await live._run_panel_and_maybe_suggest()
        live._append_utterance("second")
        live._append_utterance("third")
        await live._run_panel_and_maybe_suggest()

    assert seen == [["first"], ["second", "third"]]


@pytest.mark.asyncio
async def test_pass_with_no_new_utterances_makes_no_call():
    live, _ = make_live()
    with patch("app.cabin.live.extract_panel_delta", new=AsyncMock()) as mock:
        await live._run_panel_and_maybe_suggest()
    mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_failed_extraction_retries_the_same_utterances_next_pass():
    """A transient LLM failure must not silently drop a stretch of the consultation
    from the clinical record."""
    live, _ = make_live()
    live._append_utterance("important symptom")

    with patch(
        "app.cabin.live.extract_panel_delta",
        new=AsyncMock(side_effect=RuntimeError("boom")),
    ):
        await live._run_panel_and_maybe_suggest()

    seen: list[list[str]] = []

    async def capture(new_utterances, _panel):
        seen.append([u.text for u in new_utterances])
        return PanelDelta()

    with patch("app.cabin.live.extract_panel_delta", new=capture):
        await live._run_panel_and_maybe_suggest()

    assert seen == [["important symptom"]], "utterances were lost after a failed pass"


@pytest.mark.asyncio
async def test_analysis_failure_keeps_last_good_panel_and_transcript_flowing():
    """An LLM failure must degrade the suggestions pane, not the clinical record."""
    live, ws = make_live()
    good_panel = ClinicalPanel(symptoms=[ReportedSymptom(name="fever")])
    live.panel = good_panel
    live._append_utterance("more speech")

    with patch(
        "app.cabin.live.extract_panel_delta",
        new=AsyncMock(side_effect=RuntimeError("provider down")),
    ):
        await live._run_panel_and_maybe_suggest()

    assert (
        live.panel is good_panel
    ), "dropped the last good panel on a transient failure"
    errors = [m for m in ws.sent if m["type"] == "error"]
    assert errors and errors[0]["fatal"] is False
    assert (
        "provider down" not in errors[0]["message"]
    ), "leaked a provider error to the doctor"


@pytest.mark.asyncio
async def test_role_attribution_patches_are_idempotent_by_id():
    live, ws = make_live()
    live._append_utterance("kya dard hai?")
    live._append_utterance("haan")
    uid0, uid1 = live.utterances[0].utterance_id, live.utterances[1].utterance_id

    attribution = RoleAttribution(
        labels=[
            RoleLabel(utterance_id=uid0, role=UtteranceRole.DOCTOR, confidence=0.9),
            RoleLabel(utterance_id=uid1, role=UtteranceRole.PATIENT, confidence=0.8),
            RoleLabel(
                utterance_id="does-not-exist",
                role=UtteranceRole.ATTENDEE,
                confidence=0.5,
            ),
        ]
    )
    with patch(
        "app.cabin.live.attribute_roles", new=AsyncMock(return_value=attribution)
    ):
        await live._run_role_attribution()

    assert live.utterances[0].role == UtteranceRole.DOCTOR
    assert live.utterances[1].role == UtteranceRole.PATIENT
    patches = [m for m in ws.sent if m["type"] == "utterance_role"]
    assert len(patches) == 2, "emitted a patch for an unknown utterance_id"


# ── audio archival ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_archived_audio_is_valid_16k_mono_pcm16_wav():
    """postprocess.rediarize re-reads this file, so the header has to be right."""
    live, _ = make_live()
    live._write_spool(b"\x01\x02" * 800)
    live._write_spool(b"\x03\x04" * 800)
    captured = {}

    async def fake_upload(path, session_id, mime_type="audio/wav"):
        with open(path, "rb") as fh:
            captured["data"] = fh.read()
        captured["mime_type"] = mime_type
        return "audio/sess-1/abc.wav"

    with patch("app.cabin.live.r2.upload_audio_file", new=fake_upload):
        await live._archive_audio()

    assert live.session.audio_key == "audio/sess-1/abc.wav"
    with wave.open(io.BytesIO(captured["data"]), "rb") as wav_file:
        assert wav_file.getnchannels() == 1
        assert wav_file.getsampwidth() == 2
        assert wav_file.getframerate() == 16000
        assert wav_file.getnframes() == 1600


# ── session cap ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_analysis_loop_stops_at_the_session_cap(monkeypatch):
    """A forgotten session must not hold an ElevenLabs socket open indefinitely."""
    monkeypatch.setattr(settings, "CABIN_MAX_SESSION_MINUTES", 0)
    live, _ = make_live()
    live._session_started_at = 0.0

    await asyncio.wait_for(live._analysis_loop(), timeout=2.0)

    assert live._stopped.is_set()
    assert live._end_reason == "ended"


# ── reconciliation: keeping the record correct, not just cheap ────────────


@pytest.mark.asyncio
async def test_periodic_reconciliation_fires_and_sees_everything(monkeypatch):
    """Deltas cannot revise or drop an entry. Without a periodic full pass the panel
    would carry a superseded value for the rest of the consultation."""
    monkeypatch.setattr(settings, "CABIN_PANEL_RECONCILE_EVERY_N_PASSES", 3)
    live, _ = make_live()

    delta_calls: list[list[str]] = []
    reconcile_calls: list[list[str]] = []

    async def fake_delta(new_utterances, _panel):
        delta_calls.append([u.text for u in new_utterances])
        return PanelDelta()

    async def fake_reconcile(utterances, _panel):
        reconcile_calls.append([u.text for u in utterances])
        return ClinicalPanel(symptoms=[ReportedSymptom(name="corrected")])

    with (
        patch("app.cabin.live.extract_panel_delta", new=fake_delta),
        patch("app.cabin.live.reconcile_panel", new=fake_reconcile),
        patch("app.cabin.live.suggest", new=AsyncMock(return_value=LiveSuggestions())),
    ):
        for i in range(3):
            live._append_utterance(f"line {i}")
            await live._run_panel_and_maybe_suggest()

    assert len(delta_calls) == 2, "expected deltas on the non-reconciling passes"
    assert len(reconcile_calls) == 1, "reconciliation did not fire on the Nth pass"
    assert reconcile_calls[0] == [
        "line 0",
        "line 1",
        "line 2",
    ], "reconciliation saw a partial transcript"
    assert [s.name for s in live.panel.symptoms] == [
        "corrected"
    ], "reconciled panel was not adopted"


@pytest.mark.asyncio
async def test_reconciliation_that_removes_an_entry_refreshes_suggestions(monkeypatch):
    """A retraction changes the clinical picture, so the differentials on screen must
    be recomputed — the delta gate can't detect a removal."""
    monkeypatch.setattr(settings, "CABIN_PANEL_RECONCILE_EVERY_N_PASSES", 1)
    live, ws = make_live()
    live.panel = ClinicalPanel(symptoms=[ReportedSymptom(name="diabetes")])
    live._append_utterance("mujhe diabetes nahi hai")

    with (
        patch(
            "app.cabin.live.reconcile_panel",
            new=AsyncMock(return_value=ClinicalPanel()),
        ),
        patch(
            "app.cabin.live.suggest", new=AsyncMock(return_value=LiveSuggestions())
        ) as mock_suggest,
    ):
        await live._run_panel_and_maybe_suggest()

    mock_suggest.assert_awaited_once()
    assert live.panel.symptoms == [], "retracted entry stayed on the panel"
    assert "suggestions" in types_of(ws)


@pytest.mark.asyncio
async def test_session_end_reconciles_before_persisting():
    """The persisted panel is what goes downstream to coding and insurance, so it must
    reflect the whole conversation rather than an accumulation of increments."""
    live, _ = make_live()
    live._append_utterance("teen din se bukhar")
    live.panel = ClinicalPanel(
        symptoms=[ReportedSymptom(name="fever", detail="3 days")]
    )

    final = ClinicalPanel(symptoms=[ReportedSymptom(name="fever", detail="3 weeks")])
    with patch(
        "app.cabin.live.reconcile_panel", new=AsyncMock(return_value=final)
    ) as mock:
        await live._final_reconcile()

    mock.assert_awaited_once()
    assert live.panel.symptoms[0].detail == "3 weeks"


@pytest.mark.asyncio
async def test_failed_final_reconciliation_keeps_the_incremental_panel():
    """Best-effort: a failure here must not leave the session with no panel at all."""
    live, _ = make_live()
    live._append_utterance("something")
    incremental = ClinicalPanel(symptoms=[ReportedSymptom(name="fever")])
    live.panel = incremental

    with patch(
        "app.cabin.live.reconcile_panel",
        new=AsyncMock(side_effect=RuntimeError("down")),
    ):
        await live._final_reconcile()

    assert live.panel is incremental


@pytest.mark.asyncio
async def test_final_reconcile_skipped_when_nothing_was_said():
    live, _ = make_live()
    with patch("app.cabin.live.reconcile_panel", new=AsyncMock()) as mock:
        await live._final_reconcile()
    mock.assert_not_awaited()


# ── lease renewal ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_lease_is_renewed_from_the_analysis_loop(monkeypatch):
    """Renewal shares the loop that already heartbeats the session rather than adding
    a fifth task."""
    monkeypatch.setattr(settings, "CABIN_LEASE_RENEW_SECS", 0.0)
    live, _ = make_live()
    live._session_started_at = time.monotonic()  # else the session cap ends the loop
    renew = AsyncMock(return_value=True)

    with patch("app.cabin.live.leases.renew", new=renew):
        task = asyncio.create_task(live._analysis_loop())
        await asyncio.sleep(0.6)
        live._stopped.set()
        await task

    renew.assert_awaited_with(live.session.session_id)


@pytest.mark.asyncio
async def test_a_lost_lease_does_not_end_the_session(monkeypatch):
    """Killing a live consultation over a lost lease would destroy clinical data —
    strictly worse than the duplicate connection it would prevent."""
    monkeypatch.setattr(settings, "CABIN_LEASE_RENEW_SECS", 0.0)
    live, ws = make_live()
    live._session_started_at = time.monotonic()

    with patch("app.cabin.live.leases.renew", new=AsyncMock(return_value=False)):
        task = asyncio.create_task(live._analysis_loop())
        await asyncio.sleep(0.6)
        assert not live._stopped.is_set()
        live._stopped.set()
        await task

    assert "error" not in types_of(ws)


# ── cost telemetry ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_cost_is_recorded_after_the_final_reconciliation():
    """The reconciliation is itself an LLM call, so it has to be counted before the
    flush that persists the total."""
    live, _ = make_live()
    live._append_utterance("something")

    async def reconcile(utterances, panel):
        usage.record("anthropic", "claude-haiku-4-5", 1_000_000, 0)
        return ClinicalPanel()

    usage.bind(live._usage_calls)
    with patch("app.cabin.live.reconcile_panel", new=reconcile):
        await live._final_reconcile()
        live._record_cost()
    usage.bind(None)

    assert live.session.cost.calls == 1
    assert live.session.cost.input_tokens == 1_000_000
    assert live.session.cost.usd == pytest.approx(1.00)


@pytest.mark.asyncio
async def test_cost_is_zero_when_no_calls_were_made():
    live, _ = make_live()
    live._record_cost()
    assert live.session.cost.calls == 0
    assert live.session.cost.usd == 0.0
