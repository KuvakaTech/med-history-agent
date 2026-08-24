"""Regression tests for TicketVoiceSession's phase-1 (triage) decision logic.

Bug: the manual category dropdown was showing up almost every real session
because the code only auto-accepted a category guess when the LLM
self-reported confidence == "high" (which real model output rarely commits
to), and phase 1 never exited early because it relied solely on the LLM's
own is_complete flag instead of checking what was actually already known.
"""
from __future__ import annotations

import os
from unittest.mock import AsyncMock, MagicMock, patch

os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-for-pytest-only")

import pytest

from app.ticketing import session_store as ss
from app.ticketing.models import TicketCategory, TicketSession
from app.ticketing.voice_session import _SILENCE_TIMEOUT, TicketVoiceSession


@pytest.fixture(autouse=True)
def isolate_ticket_session_store(monkeypatch):
    def unavailable():
        raise RuntimeError("MongoDB intentionally unavailable in tests")

    monkeypatch.setattr(ss, "_col", unavailable)
    yield


_CATEGORIES = [
    TicketCategory(hospital_id="h1", key="general_medicine", label="General Medicine"),
    TicketCategory(hospital_id="h1", key="orthopedics", label="Orthopaedics"),
]


def _make_voice_session() -> TicketVoiceSession:
    session = TicketSession(hospital_id="h1", patient_id="p1")
    vs = TicketVoiceSession(session=session, ws=MagicMock(), categories=_CATEGORIES)
    vs._send = AsyncMock()
    vs._speak_and_wait = AsyncMock()
    return vs


class _FakeTriageEngine:
    """Replays one canned response per call to next_turn_stream."""

    def __init__(self, responses):
        self._responses = list(responses)

    async def opening_question(self) -> str:
        return "Namaste! Aapka naam kya hai?"

    async def next_turn_stream(self, session, answer, **kwargs):
        done = self._responses.pop(0)
        yield done


@pytest.mark.asyncio
async def test_low_confidence_category_is_auto_accepted_no_dropdown():
    """A concrete but merely 'low' confidence guess should NOT trigger the
    manual dropdown — only 'none' means the model genuinely has no clue."""
    vs = _make_voice_session()
    vs._collect_patient_answer = AsyncMock(return_value="Ghutne mein dard hai, main Rahul hoon, 34 saal")

    fake_engine = _FakeTriageEngine([
        {
            "__done__": True,
            "is_complete": False,
            "question_text": "",
            "patient_name": "Rahul",
            "patient_age": 34,
            "category_guess": "orthopedics",
            "category_label": "Orthopaedics",
            "category_confidence": "low",
            "new_flags": [],
        },
    ])

    with patch("app.ticketing.voice_session.TriageEngine", return_value=fake_engine):
        await vs._run_triage()

    # Exited after the first turn, not all 3 — nothing left to ask about.
    assert vs._collect_patient_answer.call_count == 1
    assert vs.session.category is not None
    assert vs.session.category.key == "orthopedics"
    assert vs.session.category.source == "auto"
    assert vs.session.phase == "consultation"

    sent_types = [call.args[0]["type"] for call in vs._send.call_args_list]
    assert "category_manual_required" not in sent_types
    assert "category_identified" in sent_types


@pytest.mark.asyncio
async def test_none_confidence_after_max_turns_shows_manual_dropdown():
    """Only a genuine 'none' confidence through all 3 turns should fall back
    to the manual dropdown."""
    vs = _make_voice_session()
    vs._collect_patient_answer = AsyncMock(return_value="Bas theek nahi lag raha")
    vs._wait_for_category_selection = AsyncMock(
        return_value={"key": "general_medicine", "label": "General Medicine"}
    )

    unresolved = {
        "__done__": True,
        "is_complete": False,
        "question_text": "Kuch aur bataiye?",
        "patient_name": "declined",
        "patient_age": None,
        "category_guess": None,
        "category_label": None,
        "category_confidence": "none",
        "new_flags": [],
    }
    forced_final = {**unresolved, "is_complete": True, "question_text": ""}

    fake_engine = _FakeTriageEngine([unresolved, unresolved, forced_final])

    with patch("app.ticketing.voice_session.TriageEngine", return_value=fake_engine):
        await vs._run_triage()

    assert vs._collect_patient_answer.call_count == 3
    vs._wait_for_category_selection.assert_awaited_once()
    assert vs.session.category.key == "general_medicine"
    assert vs.session.category.source == "manual"

    sent_types = [call.args[0]["type"] for call in vs._send.call_args_list]
    assert "category_manual_required" in sent_types


@pytest.mark.asyncio
async def test_premature_is_complete_flag_is_ignored_when_nothing_resolved():
    """Regression: the LLM's meta call can (and did, in production) return
    is_complete=true on turn 1 even though nothing was actually resolved --
    e.g. when STT failed to catch the patient's answer at all. That flag must
    NOT be trusted on its own; only a verified name+age+category, or genuinely
    reaching the last allowed turn, should end phase 1."""
    vs = _make_voice_session()
    vs._collect_patient_answer = AsyncMock(return_value="<inaudible>")
    vs._wait_for_category_selection = AsyncMock(
        return_value={"key": "general_medicine", "label": "General Medicine"}
    )

    # Turn 1: STT failed, nothing resolved, but the LLM wrongly claims complete.
    premature = {
        "__done__": True,
        "is_complete": True,
        "question_text": "Sorry, I didn't catch your name. Could you repeat it?",
        "patient_name": None,
        "patient_age": None,
        "category_guess": None,
        "category_label": None,
        "category_confidence": "none",
        "new_flags": [],
    }
    unresolved = {**premature, "is_complete": False}
    forced_final = {**unresolved, "is_complete": True, "question_text": ""}

    fake_engine = _FakeTriageEngine([premature, unresolved, forced_final])

    with patch("app.ticketing.voice_session.TriageEngine", return_value=fake_engine):
        await vs._run_triage()

    # Must have kept asking through all 3 turns, not stopped after turn 1.
    assert vs._collect_patient_answer.call_count == 3
    vs._wait_for_category_selection.assert_awaited_once()


@pytest.mark.asyncio
async def test_silence_retry_reasks_same_question_then_succeeds():
    """A stall (patient never spoke) should re-ask the same question, not
    give up immediately or move on to a different one."""
    vs = _make_voice_session()
    vs._collect_patient_answer = AsyncMock(side_effect=[_SILENCE_TIMEOUT, "Mera naam Rahul hai"])

    answer = await vs._collect_answer_with_silence_retry("Aapka naam kya hai?", turn=0)

    assert answer == "Mera naam Rahul hai"
    assert vs._collect_patient_answer.call_count == 2
    vs._speak_and_wait.assert_awaited_once_with("Aapka naam kya hai?", 0)
    sent_types = [call.args[0]["type"] for call in vs._send.call_args_list]
    assert "error" not in sent_types


@pytest.mark.asyncio
async def test_silence_retry_exhausted_sends_fatal_error_and_gives_up():
    """Persistent silence should eventually stop retrying and surface a
    fatal, actionable error instead of hanging or looping forever."""
    vs = _make_voice_session()
    vs._collect_patient_answer = AsyncMock(return_value=_SILENCE_TIMEOUT)

    answer = await vs._collect_answer_with_silence_retry("Aapka naam kya hai?", turn=0)

    assert answer is None
    assert vs._collect_patient_answer.call_count == 3  # 1 initial + 2 retries
    assert vs._speak_and_wait.await_count == 2  # re-asked twice, not a 3rd time
    error_calls = [c.args[0] for c in vs._send.call_args_list if c.args[0]["type"] == "error"]
    assert len(error_calls) == 1
    assert error_calls[0]["fatal"] is True
