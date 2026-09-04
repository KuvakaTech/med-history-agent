"""Offline tests for post-call Claude extraction."""
from __future__ import annotations

import os
from unittest.mock import AsyncMock, patch

os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-for-pytest-only")

import pytest

from app.ticketing import patient_store as ps
from app.ticketing import session_store as ss
from app.ticketing.models import TicketCategory, TicketSession, TicketTranscriptEntry
from app.ticketing.post_call_extract import (
    ExtractedFlag,
    ExtractedQA,
    PostCallExtract,
    format_transcript,
    run_post_call_extract,
)


@pytest.fixture(autouse=True)
def isolate_stores(monkeypatch):
    def unavailable():
        raise RuntimeError("MongoDB intentionally unavailable in tests")

    monkeypatch.setattr(ss, "_col", unavailable)
    monkeypatch.setattr(ps, "_col", unavailable)
    ss._mongo_write_failed = True
    ps._mongo_write_failed = True
    ss._mem.clear()
    ps._mem.clear()
    ps._phone_index.clear()
    yield
    ss._mem.clear()
    ps._mem.clear()
    ps._phone_index.clear()
    ss._mongo_write_failed = False
    ps._mongo_write_failed = False


_CATEGORIES = [
    TicketCategory(hospital_id="h1", key="orthopedics", label="Orthopaedics"),
    TicketCategory(hospital_id="h1", key="general_medicine", label="General Medicine"),
]


def test_format_transcript_skips_empty():
    entries = [
        TicketTranscriptEntry(speaker="agent", text="Namaste"),
        TicketTranscriptEntry(speaker="user", text="  "),
        TicketTranscriptEntry(speaker="user", text="Rahul hoon"),
    ]
    text = format_transcript(entries)
    assert "Agent: Namaste" in text
    assert "Patient: Rahul hoon" in text
    assert text.count("Patient:") == 1


@pytest.mark.asyncio
async def test_empty_transcript_marks_partial():
    session = TicketSession(hospital_id="h1", patient_id="p1")
    result = await run_post_call_extract(session, _CATEGORIES)
    assert result.status == "partial"
    assert result.phase == "result"
    assert result.ended_at is not None


@pytest.mark.asyncio
async def test_extract_rebuilds_qa_flags_and_persists_patient():
    patient = await ps.ticket_patient_store.upsert(phone="9876543210", gender="male")
    session = TicketSession(
        hospital_id="h1",
        patient_id=patient.patient_id,
        gender="male",
    )
    session.transcript = [
        TicketTranscriptEntry(speaker="agent", text="Aapka naam?"),
        TicketTranscriptEntry(speaker="user", text="Rahul, 34 saal, ghutne dard"),
    ]
    extracted = PostCallExtract(
        patient_name="Rahul",
        patient_age=34,
        address="Berasia Road",
        guardian_name="Suresh",
        category_key="orthopedics",
        category_label="Orthopaedics",
        qa_log=[
            ExtractedQA(question="Aapka naam?", answer="Rahul, 34 saal, ghutne dard"),
        ],
        flags=[ExtractedFlag(flag_type="NOTE", description="Knee pain")],
    )

    with patch("app.ticketing.post_call_extract.llm.complete_structured", AsyncMock(return_value=extracted)):
        with patch(
            "app.ticketing.post_call_extract.SummarizationService.summarize",
            AsyncMock(return_value={"assessment": "knee pain", "full_transcript": "x"}),
        ):
            result = await run_post_call_extract(session, _CATEGORIES)

    assert result.status == "completed"
    assert result.turn_count == 1
    assert result.qa_log[0].answer == "Rahul, 34 saal, ghutne dard"
    assert result.flags[0].flag_type == "NOTE"
    assert result.category is not None
    assert result.category.key == "orthopedics"
    assert result.summary["assessment"] == "knee pain"

    stored = await ps.ticket_patient_store.get(patient.patient_id)
    assert stored is not None
    assert stored.name == "Rahul"
    assert stored.age == 34
    assert stored.address == "Berasia Road"
    assert stored.guardian_name == "Suresh"
    assert result.address == "Berasia Road"
    assert result.guardian_name == "Suresh"


@pytest.mark.asyncio
async def test_extract_llm_failure_still_summarizes_when_possible():
    session = TicketSession(hospital_id="h1", patient_id="p1")
    session.transcript = [
        TicketTranscriptEntry(speaker="user", text="dard hai"),
    ]
    with patch(
        "app.ticketing.post_call_extract.llm.complete_structured",
        AsyncMock(side_effect=RuntimeError("llm down")),
    ):
        with patch(
            "app.ticketing.post_call_extract.SummarizationService.summarize",
            AsyncMock(return_value={"assessment": None}),
        ):
            result = await run_post_call_extract(session, _CATEGORIES)
    assert result.status == "completed"
    assert result.qa_log == []
    assert result.summary == {"assessment": None}


@pytest.mark.asyncio
async def test_extract_leaves_missing_address_and_guardian_null():
    patient = await ps.ticket_patient_store.upsert(phone="9123456780", gender="female")
    session = TicketSession(
        hospital_id="h1",
        patient_id=patient.patient_id,
        gender="female",
    )
    session.transcript = [
        TicketTranscriptEntry(speaker="user", text="Priya, 28 saal, sir dard"),
    ]
    extracted = PostCallExtract(
        patient_name="Priya",
        patient_age=28,
        address=None,
        guardian_name=None,
        category_key="general_medicine",
        category_label="General Medicine",
        qa_log=[ExtractedQA(question="Naam?", answer="Priya, 28 saal, sir dard")],
        flags=[],
    )
    with patch(
        "app.ticketing.post_call_extract.llm.complete_structured",
        AsyncMock(return_value=extracted),
    ):
        with patch(
            "app.ticketing.post_call_extract.SummarizationService.summarize",
            AsyncMock(return_value={"assessment": "headache"}),
        ):
            result = await run_post_call_extract(session, _CATEGORIES)

    stored = await ps.ticket_patient_store.get(patient.patient_id)
    assert stored is not None
    assert stored.address is None
    assert stored.guardian_name is None
    assert result.address is None
    assert result.guardian_name is None
