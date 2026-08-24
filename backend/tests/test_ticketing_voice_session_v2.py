"""Regression tests for TicketVoiceSessionV2. No live Gemini, no MongoDB."""
from __future__ import annotations

import array
import asyncio
import os
from unittest.mock import AsyncMock, MagicMock, patch

os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-for-pytest-only")

import pytest

from app.core.config import settings
from app.ticketing import session_store as ss
from app.ticketing.gemini_live import LiveEvent
from app.ticketing.models import TicketCategory, TicketSession, TicketTranscriptEntry
from app.ticketing.triage_engine import TriageMeta
from app.ticketing.voice_session_v2 import (
    TicketVoiceSessionV2,
    _DUCK_RMS_THRESHOLD,
    acquire_live_slot,
    pcm16_rms,
    release_live_slot,
    reset_live_slots,
)


@pytest.fixture(autouse=True)
def isolate_ticket_session_store(monkeypatch):
    def unavailable():
        raise RuntimeError("MongoDB intentionally unavailable in tests")

    monkeypatch.setattr(ss, "_col", unavailable)
    ss._mongo_write_failed = True
    yield
    ss._mongo_write_failed = False
    reset_live_slots()


_CATEGORIES = [
    TicketCategory(hospital_id="h1", key="general_medicine", label="General Medicine"),
    TicketCategory(hospital_id="h1", key="orthopedics", label="Orthopaedics"),
]


def _make_v2() -> TicketVoiceSessionV2:
    session = TicketSession(hospital_id="h1", patient_id="p1")
    vs = TicketVoiceSessionV2(session=session, ws=MagicMock(), categories=_CATEGORIES)
    vs._send = AsyncMock()
    vs._live = MagicMock()
    vs._live.send_tool_response = AsyncMock()
    vs._live.send_audio = AsyncMock()
    return vs


def test_pcm16_rms_zero_and_loud():
    assert pcm16_rms(b"") == 0.0
    assert pcm16_rms(bytes(320)) == 0.0
    loud = array.array("h", [12000] * 160).tobytes()
    assert pcm16_rms(loud) > _DUCK_RMS_THRESHOLD


@pytest.mark.asyncio
async def test_live_slot_cap_per_hospital(monkeypatch):
    reset_live_slots()
    monkeypatch.setattr(settings, "TICKETING_MAX_CONCURRENT_LIVE_SESSIONS_PER_HOSPITAL", 2)
    assert await acquire_live_slot("h1")
    assert await acquire_live_slot("h1")
    assert not await acquire_live_slot("h1")
    assert await acquire_live_slot("h2")
    await release_live_slot("h1")
    assert await acquire_live_slot("h1")


@pytest.mark.asyncio
async def test_finish_triage_high_confidence_auto_accepts():
    vs = _make_v2()
    await vs._on_finish_triage(
        {
            "patient_name": "Rahul",
            "patient_age": 34,
            "routing_summary": "left knee pain for a week",
            "category_key": "orthopedics",
            "confidence": "high",
        },
        "call-1",
    )
    assert vs._category_key == "orthopedics"
    assert vs._patient_name == "Rahul"
    assert vs._phase_done.is_set()
    types_sent = [c.args[0]["type"] for c in vs._send.call_args_list]
    assert "category_identified" in types_sent


@pytest.mark.asyncio
async def test_finish_triage_low_confidence_does_not_auto_accept():
    vs = _make_v2()
    await vs._on_finish_triage(
        {
            "patient_name": "Rahul",
            "patient_age": 34,
            "routing_summary": "not sure",
            "category_key": "orthopedics",
            "confidence": "low",
        },
        "call-2",
    )
    assert vs._category_key is None
    assert not vs._phase_done.is_set()


@pytest.mark.asyncio
async def test_finish_triage_invalid_key_rejected():
    vs = _make_v2()
    await vs._on_finish_triage(
        {
            "patient_name": "Rahul",
            "patient_age": 34,
            "routing_summary": "rash",
            "category_key": "not_a_dept",
            "confidence": "high",
        },
        "call-3",
    )
    assert vs._category_key is None


@pytest.mark.asyncio
async def test_barge_in_emits_interrupt():
    vs = _make_v2()
    vs._agent_playing = True
    await vs._handle_live_event(LiveEvent(kind="interrupted"), "triage")
    assert vs._agent_playing is False
    types_sent = [c.args[0]["type"] for c in vs._send.call_args_list]
    assert "interrupt" in types_sent


@pytest.mark.asyncio
async def test_user_transcript_increments_turn_count():
    vs = _make_v2()
    await vs._handle_live_event(
        LiveEvent(kind="user_transcript_final", text="mera naam Rahul hai"),
        "triage",
    )
    assert vs.session.turn_count == 1
    assert vs._user_turns_this_phase == 1
    assert vs.session.transcript == []  # queued, worker not running
    # drain via enqueue path: worker not running so entry is on the queue
    entry = vs._transcript_q.get_nowait()
    assert entry.speaker == "user"
    assert "Rahul" in entry.text


@pytest.mark.asyncio
async def test_ducking_drops_quiet_frames_while_agent_playing():
    vs = _make_v2()
    vs._agent_playing = True
    task = asyncio.create_task(vs._relay_client_to_gemini())
    await vs._audio_q.put(bytes(320))
    await asyncio.sleep(0.05)
    vs._live.send_audio.assert_not_called()
    loud = array.array("h", [12000] * 160).tobytes()
    await vs._audio_q.put(loud)
    await asyncio.sleep(0.05)
    vs._live.send_audio.assert_called()
    vs._stopped.set()
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
async def test_triage_ceiling_fallback_accepts_valid_guess():
    vs = _make_v2()
    vs.session.transcript.append(
        TicketTranscriptEntry(speaker="user", text="ghutne mein dard hai")
    )
    meta = TriageMeta(
        patient_name="Rahul",
        patient_age=34,
        category_guess="orthopedics",
        category_label="Orthopaedics",
        category_confidence="low",
    )
    with patch(
        "app.ticketing.voice_session_v2.extract_triage_fallback",
        AsyncMock(return_value=meta),
    ):
        await vs._triage_turn_ceiling()
    assert vs._category_key == "orthopedics"
    assert vs._phase_done.is_set()


@pytest.mark.asyncio
async def test_session_minutes_watchdog(monkeypatch):
    vs = _make_v2()
    monkeypatch.setattr(settings, "TICKETING_MAX_SESSION_MINUTES", 0)
    await vs._watchdog()
    assert vs._stopped.is_set()
    assert vs._phase_done.is_set()
