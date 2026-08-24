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
from app.ticketing.voice_session import TicketVoiceSession


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
