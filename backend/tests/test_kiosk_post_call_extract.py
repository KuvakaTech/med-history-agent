"""Tests for kiosk post-call grievance extract."""
from __future__ import annotations

import os
from unittest.mock import AsyncMock, patch

os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-for-pytest-only")

import pytest

from app.kiosk.models import KioskCentre, KioskSession, KioskTranscriptEntry
from app.kiosk.post_call_extract import (
    GrievanceExtract,
    _extract_prompt_for_centre,
    format_transcript,
    run_post_call_extract,
)


def test_format_transcript():
    entries = [
        KioskTranscriptEntry(speaker="agent", text="Namaste"),
        KioskTranscriptEntry(speaker="user", text="Bijli ka bill zyada"),
    ]
    text = format_transcript(entries)
    assert "Agent: Namaste" in text
    assert "Citizen: Bijli ka bill zyada" in text


@pytest.mark.asyncio
async def test_empty_transcript_marks_partial():
    session = KioskSession(
        centre_id="c1",
        phone="9876543210",
        language="hi",
    )
    centre = KioskCentre(slug="varanasi-jan-sunwai", name="Jan Sunwai")
    with patch(
        "app.kiosk.session_store.kiosk_session_store.update",
        new_callable=AsyncMock,
    ) as mock_update:
        out = await run_post_call_extract(session, centre)
        assert out.status == "partial"
        mock_update.assert_called_once()


@pytest.mark.asyncio
async def test_extract_assigns_complaint_number():
    session = KioskSession(
        centre_id="c1",
        phone="9876543210",
        language="hi",
        transcript=[
            KioskTranscriptEntry(speaker="user", text="Paani nahi aata"),
            KioskTranscriptEntry(speaker="agent", text="Kab se?"),
        ],
    )
    centre = KioskCentre(
        slug="varanasi-jan-sunwai",
        name="Varanasi Jan Sunwai",
        complaint_prefix="JS-VNS",
    )
    extracted = GrievanceExtract(
        full_name="Ram Kumar",
        category="water",
        confirmed_summary="No water supply for 2 weeks",
        department_tag="water",
        urgency="normal",
    )
    with patch(
        "app.agent.llm.complete_structured",
        new_callable=AsyncMock,
        return_value=extracted,
    ):
        with patch(
            "app.kiosk.post_call_extract.next_complaint_number",
            new_callable=AsyncMock,
            return_value="JS-VNS-20250825-00001",
        ):
            with patch(
                "app.kiosk.session_store.kiosk_session_store.update",
                new_callable=AsyncMock,
            ):
                out = await run_post_call_extract(session, centre)
    assert out.status == "completed"
    assert out.complaint_number == "JS-VNS-20250825-00001"
    assert out.grievance is not None
    assert out.grievance.full_name == "Ram Kumar"


def test_nagar_nigam_extract_prompt():
    centre = KioskCentre(slug="varanasi-nagar-nigam", name="Nagar Nigam")
    prompt = _extract_prompt_for_centre(centre)
    assert "Nagar Nigam" in prompt
    assert "jal_kal_water" in prompt
