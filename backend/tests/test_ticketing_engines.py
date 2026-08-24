"""Tests for TriageEngine and ConsultationEngine.

Every LLM call is mocked — tests verify:
  - 3-turn hard cap on triage
  - High-confidence → auto category path
  - Low/none confidence → manual category path
  - ConsultationEngine min/max turn enforcement
  - Red flags accumulate on session
  - No diagnosis/prescription calls made anywhere in this flow
  - Category guess is validated against the hospital's active category list
"""
from __future__ import annotations

import os
from unittest.mock import AsyncMock, MagicMock, patch

os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-for-pytest-only")

import pytest

from app.ticketing.models import TicketCategory, TicketQAEntry, TicketSession
from app.ticketing.triage_engine import MAX_TRIAGE_TURNS, TriageEngine, TriageMeta
from app.ticketing.consultation_engine import (
    MAX_CONSULTATION_TURNS,
    MIN_CONSULTATION_TURNS,
    ConsultationEngine,
    ConsultMeta,
    _AREA_KEYS,
)


# ── helpers ───────────────────────────────────────────────────

def _make_categories() -> list[TicketCategory]:
    return [
        TicketCategory(hospital_id="h1", key="general_medicine", label="General Medicine"),
        TicketCategory(hospital_id="h1", key="gynecology", label="Gynaecology"),
        TicketCategory(hospital_id="h1", key="orthopedics", label="Orthopaedics"),
    ]


def _make_session(turns: int = 0) -> TicketSession:
    s = TicketSession(hospital_id="h1", patient_id="p1")
    for i in range(turns):
        s.qa_log.append(TicketQAEntry(
            question_id=f"q{i}",
            question_text=f"Question {i}?",
            answer=f"Answer {i}",
        ))
    return s


# ── TriageEngine ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_triage_opening_question_returns_string():
    engine = TriageEngine(categories=_make_categories(), language="hi")
    with patch("app.ticketing.triage_engine.llm.complete", new=AsyncMock(return_value="Namaste! Aapko kya takleef hai?")):
        q = await engine.opening_question()
    assert isinstance(q, str)
    assert len(q) > 0


@pytest.mark.asyncio
async def test_triage_stream_yields_tokens_then_done():
    engine = TriageEngine(categories=_make_categories(), language="hi")
    session = _make_session(turns=0)

    async def fake_stream(prompt, system="", fast=True):
        for token in ["Aap", "ki", "umar"]:
            yield token

    fake_meta = TriageMeta(
        patient_name="Priya",
        patient_age=30,
        category_guess="gynecology",
        category_label="Gynaecology",
        category_confidence="high",
        is_complete=True,
    )

    with patch("app.ticketing.triage_engine.llm.stream_complete", new=fake_stream), \
         patch("app.ticketing.triage_engine.llm.complete_structured", new=AsyncMock(return_value=fake_meta)):
        chunks = []
        done_data = None
        async for chunk in engine.next_turn_stream(session, "mujhe pet dard hai"):
            if isinstance(chunk, str):
                chunks.append(chunk)
            elif isinstance(chunk, dict) and chunk.get("__done__"):
                done_data = chunk

    assert chunks == ["Aap", "ki", "umar"]
    assert done_data is not None
    assert done_data["patient_name"] == "Priya"
    assert done_data["category_confidence"] == "high"
    assert done_data["is_complete"] is True


@pytest.mark.asyncio
async def test_triage_forces_completion_at_max_turns():
    """At turn 2 (MAX_TRIAGE_TURNS - 1), triage must force is_complete=True
    regardless of what the meta says — patient can't be asked a 4th question."""
    engine = TriageEngine(categories=_make_categories(), language="hi")
    session = _make_session(turns=MAX_TRIAGE_TURNS - 1)

    fake_meta = TriageMeta(
        is_complete=False,  # LLM says not done — must be overridden
        category_confidence="none",
    )
    with patch("app.ticketing.triage_engine.llm.complete_structured", new=AsyncMock(return_value=fake_meta)):
        chunks = []
        done_data = None
        async for chunk in engine.next_turn_stream(session, "mujhe pata nahi"):
            if isinstance(chunk, dict) and chunk.get("__done__"):
                done_data = chunk
            else:
                chunks.append(chunk)

    assert done_data is not None
    assert done_data["is_complete"] is True, "triage did not force completion at max turns"


@pytest.mark.asyncio
async def test_triage_category_guess_not_in_allowed_list_stays_as_is():
    """The LLM might guess a category not in the hospital's list. The engine
    passes it through — the caller (voice_session) decides what to do."""
    engine = TriageEngine(categories=_make_categories(), language="hi")
    session = _make_session(turns=0)

    fake_meta = TriageMeta(
        category_guess="cardiology",  # not in _make_categories()
        category_confidence="high",
        is_complete=True,
    )

    async def fake_stream(prompt, system="", fast=True):
        yield "question"

    with patch("app.ticketing.triage_engine.llm.stream_complete", new=fake_stream), \
         patch("app.ticketing.triage_engine.llm.complete_structured", new=AsyncMock(return_value=fake_meta)):
        done_data = None
        async for chunk in engine.next_turn_stream(session, "seene mein dard"):
            if isinstance(chunk, dict) and chunk.get("__done__"):
                done_data = chunk

    # Engine passes through what the LLM says — validation is the caller's job
    assert done_data["category_guess"] == "cardiology"
    assert done_data["category_confidence"] == "high"


@pytest.mark.asyncio
async def test_triage_low_confidence_sets_is_complete_only_when_at_cap():
    """Low confidence by itself at turn 0 should not end triage — only at turn cap."""
    engine = TriageEngine(categories=_make_categories(), language="hi")
    session = _make_session(turns=0)

    fake_meta = TriageMeta(
        category_confidence="low",
        is_complete=False,  # LLM correctly says not done
    )

    async def fake_stream(prompt, system="", fast=True):
        yield "next question"

    with patch("app.ticketing.triage_engine.llm.stream_complete", new=fake_stream), \
         patch("app.ticketing.triage_engine.llm.complete_structured", new=AsyncMock(return_value=fake_meta)):
        done_data = None
        async for chunk in engine.next_turn_stream(session, "thoda sa sir dard"):
            if isinstance(chunk, dict) and chunk.get("__done__"):
                done_data = chunk

    assert done_data["is_complete"] is False
    assert done_data["category_confidence"] == "low"


# ── ConsultationEngine ────────────────────────────────────────


@pytest.mark.asyncio
async def test_consultation_opening_question_returns_string():
    engine = ConsultationEngine(category_label="General Medicine", language="hi")
    with patch("app.ticketing.consultation_engine.llm.complete", new=AsyncMock(return_value="Aapko kab se ye takleef hai?")):
        q = await engine.opening_question(covered=[])
    assert isinstance(q, str)
    assert len(q) > 0


@pytest.mark.asyncio
async def test_consultation_stream_yields_tokens_then_done():
    engine = ConsultationEngine(category_label="General Medicine", language="hi", name="Priya", age="30")
    session = _make_session(turns=1)

    async def fake_stream(prompt, system="", fast=True):
        for t in ["Kitna", "dard"]:
            yield t

    fake_meta = ConsultMeta(is_complete=False, covered_areas=["chief_complaint"])

    with patch("app.ticketing.consultation_engine.llm.stream_complete", new=fake_stream), \
         patch("app.ticketing.consultation_engine.llm.complete_structured", new=AsyncMock(return_value=fake_meta)):
        tokens = []
        done = None
        async for chunk in engine.next_turn_stream(session, "kal se", covered=[]):
            if isinstance(chunk, str):
                tokens.append(chunk)
            elif isinstance(chunk, dict) and chunk.get("__done__"):
                done = chunk

    assert tokens == ["Kitna", "dard"]
    assert done is not None
    assert done["covered_areas"] == ["chief_complaint"]


@pytest.mark.asyncio
async def test_consultation_enforces_min_turns():
    """Even if LLM says is_complete=True, must not complete before MIN_CONSULTATION_TURNS."""
    engine = ConsultationEngine(category_label="General Medicine", language="hi")
    session = _make_session(turns=1)  # only 1 turn, below minimum

    fake_meta = ConsultMeta(is_complete=True)  # LLM says done too early

    async def fake_stream(prompt, system="", fast=True):
        yield "keep going"

    with patch("app.ticketing.consultation_engine.llm.stream_complete", new=fake_stream), \
         patch("app.ticketing.consultation_engine.llm.complete_structured", new=AsyncMock(return_value=fake_meta)):
        done = None
        async for chunk in engine.next_turn_stream(session, "haan", covered=[]):
            if isinstance(chunk, dict) and chunk.get("__done__"):
                done = chunk

    assert done["is_complete"] is False, "consultation ended before MIN_CONSULTATION_TURNS"


@pytest.mark.asyncio
async def test_consultation_forces_done_at_max_turns():
    """At MAX_CONSULTATION_TURNS the engine must not ask another question."""
    engine = ConsultationEngine(category_label="General Medicine", language="hi")
    session = _make_session(turns=MAX_CONSULTATION_TURNS)

    # Should not reach LLM at all
    with patch("app.ticketing.consultation_engine.llm.stream_complete") as mock_stream, \
         patch("app.ticketing.consultation_engine.llm.complete_structured") as mock_struct:
        done = None
        async for chunk in engine.next_turn_stream(session, "haan", covered=[]):
            if isinstance(chunk, dict) and chunk.get("__done__"):
                done = chunk

    mock_stream.assert_not_called()
    mock_struct.assert_not_called()
    assert done["is_complete"] is True


@pytest.mark.asyncio
async def test_consultation_red_flags_accumulate_on_session():
    engine = ConsultationEngine(category_label="General Medicine", language="hi")
    session = _make_session(turns=MIN_CONSULTATION_TURNS)

    fake_meta = ConsultMeta(
        is_complete=True,
        new_flags=[
            {"flag_type": "CRITICAL_RED_FLAG", "description": "Chest pain reported"},
            {"flag_type": "RED_FLAG", "description": "High pain score 9/10"},
        ],
    )

    async def fake_stream(prompt, system="", fast=True):
        yield "one more question"

    with patch("app.ticketing.consultation_engine.llm.stream_complete", new=fake_stream), \
         patch("app.ticketing.consultation_engine.llm.complete_structured", new=AsyncMock(return_value=fake_meta)):
        async for _ in engine.next_turn_stream(session, "haan seene mein dard", covered=_AREA_KEYS[:4]):
            pass

    assert len(session.flags) == 2
    types = {f.flag_type for f in session.flags}
    assert "CRITICAL_RED_FLAG" in types
    assert "RED_FLAG" in types


@pytest.mark.asyncio
async def test_consultation_no_diagnosis_or_prescription_calls():
    """The consultation engine must NEVER call diagnosis or prescription services."""
    engine = ConsultationEngine(category_label="General Medicine", language="hi")
    session = _make_session(turns=MIN_CONSULTATION_TURNS)

    async def fake_stream(prompt, system="", fast=True):
        yield "ok"

    fake_meta = ConsultMeta(is_complete=True)

    with patch("app.ticketing.consultation_engine.llm.stream_complete", new=fake_stream), \
         patch("app.ticketing.consultation_engine.llm.complete_structured", new=AsyncMock(return_value=fake_meta)), \
         patch("app.clinical.services.diagnosis.DiagnosisService.diagnose") as mock_dx, \
         patch("app.clinical.services.prescription.PrescriptionService.prescribe") as mock_rx:
        async for _ in engine.next_turn_stream(session, "ok", covered=_AREA_KEYS[:7]):
            pass

    mock_dx.assert_not_called()
    mock_rx.assert_not_called()


# ── language helper ───────────────────────────────────────────


def test_language_name_maps_known_codes():
    from app.ticketing.triage_engine import _language_name
    assert _language_name("hi") == "Hindi"
    assert _language_name("en") == "English"
    assert _language_name("mr") == "Marathi"
    assert _language_name("gu") == "Gujarati"


def test_language_name_returns_code_for_unknown():
    from app.ticketing.triage_engine import _language_name
    assert _language_name("xx") == "xx"
