"""Tests for kiosk post-call grievance extract."""
from __future__ import annotations

import os
from unittest.mock import AsyncMock, patch

os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-for-pytest-only")

import pytest

from app.kiosk.models import KioskCentre, KioskSession, KioskTranscriptEntry
from app.kiosk.post_call_extract import (
    GrievanceExtract,
    JanSunwaiV3MetaExtract,
    _JAN_SUNWAI_V3_META_EXTRACT_PROMPT,
    _extract_prompt_for_centre,
    _resolve_v3_modes,
    fill_print_placeholders,
    format_transcript,
    parse_jansunwai_record,
    run_post_call_extract,
    template_v3_print_document,
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


def test_jan_sunwai_extract_prompt():
    centre = KioskCentre(slug="varanasi-jan-sunwai", name="Jan Sunwai")
    prompt = _extract_prompt_for_centre(centre)
    assert "Jan Sunwai" in prompt
    assert "land_revenue" in prompt
    assert "khasra" in prompt
    assert "out_of_scope" in prompt
    assert "route_to" in prompt


def test_nagar_nigam_extract_prompt():
    centre = KioskCentre(slug="varanasi-nagar-nigam", name="Nagar Nigam")
    prompt = _extract_prompt_for_centre(centre)
    assert "Nagar Nigam" in prompt
    assert "jal_kal_water" in prompt
    assert "out_of_scope" in prompt
    assert "route_to" in prompt
    assert "service_request" in prompt
    assert "pvvnl_electricity_bill" in prompt


def test_barwani_jan_sunwai_extract_prompt():
    centre = KioskCentre(
        slug="barwani-jan-sunwai",
        name="Barwani Jan Sunwai",
        prompt_file="barwani_jan_sunwai",
    )
    prompt = _extract_prompt_for_centre(centre)
    assert "Barwani" in prompt
    assert "Sendhwa" in prompt
    assert "MPPKVVCL" in prompt
    assert "punarvas" in prompt
    assert "Sadar" not in prompt
    assert "PVVNL" not in prompt


def test_jan_sunwai_v3_meta_extract_prompt():
    assert "application_letter" in _JAN_SUNWAI_V3_META_EXTRACT_PROMPT
    assert "info_sheet" in _JAN_SUNWAI_V3_META_EXTRACT_PROMPT
    assert "Do NOT generate the printable letter body" in _JAN_SUNWAI_V3_META_EXTRACT_PROMPT
    assert "mixed" in _JAN_SUNWAI_V3_META_EXTRACT_PROMPT.lower()


def test_resolve_v3_modes_mixed_forces_application_letter():
    session = KioskSession(centre_id="c1", finish_print_mode="info_sheet")
    extracted = JanSunwaiV3MetaExtract(
        session_type="mixed",
        print_mode="info_sheet",
    )
    session_type, print_mode = _resolve_v3_modes(session, extracted, None)
    assert session_type == "mixed"
    assert print_mode == "application_letter"


def test_resolve_v3_modes_mixed_overrides_record_info_sheet():
    session = KioskSession(centre_id="c1")
    extracted = JanSunwaiV3MetaExtract(session_type="complaint", print_mode="application_letter")
    record = {"session_type": "mixed", "print_mode": "info_sheet"}
    session_type, print_mode = _resolve_v3_modes(session, extracted, record)
    assert session_type == "mixed"
    assert print_mode == "application_letter"


def test_fill_print_placeholders():
    out = fill_print_placeholders("दिनांक: {{DATE}} समय: {{TIME}}")
    assert "{{DATE}}" not in out
    assert "{{TIME}}" not in out
    assert "{DATE}" not in out
    assert "{TIME}" not in out
    assert "दिनांक:" in out


def test_fill_print_placeholders_single_brace_tokens():
    out = fill_print_placeholders("दिनांक: {DATE}   समय: {TIME}")
    assert "{DATE}" not in out
    assert "{TIME}" not in out
    assert "दिनांक:" in out


def test_parse_jansunwai_record():
    transcript = (
        'Agent: done\n<<<JANSUNWAI_RECORD\n'
        '{"session_type":"information","print_mode":"info_sheet",'
        '"print_document_text":"आपका प्रश्न"}\n'
        "JANSUNWAI_RECORD>>>"
    )
    record = parse_jansunwai_record(transcript)
    assert record is not None
    assert record["session_type"] == "information"
    assert record["print_mode"] == "info_sheet"


def test_template_v3_application_letter():
    meta = JanSunwaiV3MetaExtract(
        full_name="Ram Kumar",
        father_guardian_name="Shyam Kumar",
        confirmed_summary="Ganda paani aa raha hai",
        department_tag="water",
    )
    text = template_v3_print_document(meta, "application_letter")
    assert "जन सुनवाई केंद्र" in text
    assert "Ram Kumar" in text
    assert "प्रार्थना पत्र" in text
    assert "{{DATE}}" in text


def test_template_v3_info_sheet():
    meta = JanSunwaiV3MetaExtract(
        chief_complaint_or_query="Nivas praman ke liye kya document",
        department_tag="certificates",
    )
    text = template_v3_print_document(meta, "info_sheet")
    assert "जानकारी" not in text or "आपका प्रश्न" in text
    assert "आपका प्रश्न" in text


@pytest.mark.asyncio
async def test_v3_complaint_assigns_number_and_letter():
    session = KioskSession(
        centre_id="c1",
        phone="9876543210",
        language="hi",
        finish_print_mode="application_letter",
        finish_session_type="complaint",
        transcript=[
            KioskTranscriptEntry(speaker="user", text="Kabza ho gaya"),
            KioskTranscriptEntry(speaker="agent", text="Naam bataiye"),
        ],
    )
    centre = KioskCentre(
        slug="varanasi-jan-sunwai-v3",
        name="Varanasi Jan Sunwai v3",
        prompt_file="jan_sunwai_v3_system.txt",
        complaint_prefix="JS-VNS",
    )
    meta = JanSunwaiV3MetaExtract(
        full_name="Ram Kumar",
        session_type="complaint",
        print_mode="application_letter",
        confirmed_summary="Kabza on land",
        department_tag="land_revenue",
        urgency="normal",
    )
    with patch(
        "app.agent.llm.complete_structured",
        new_callable=AsyncMock,
        return_value=meta,
    ):
        with patch(
            "app.agent.llm.complete",
            new_callable=AsyncMock,
            return_value="                 जन सुनवाई केंद्र\nदिनांक: {{DATE}}",
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
    assert out.grievance.print_mode == "application_letter"
    assert out.grievance.print_document_text
    assert "{{DATE}}" not in out.grievance.print_document_text
    assert "JS-VNS" not in (out.grievance.print_document_text or "")


@pytest.mark.asyncio
async def test_v3_information_skips_complaint_number():
    session = KioskSession(
        centre_id="c1",
        phone="9876543210",
        language="hi",
        finish_print_mode="info_sheet",
        finish_session_type="information",
        transcript=[
            KioskTranscriptEntry(
                speaker="user",
                text="Nivas praman ke liye kya document lagega",
            ),
        ],
    )
    centre = KioskCentre(
        slug="varanasi-jan-sunwai-v3",
        name="Varanasi Jan Sunwai v3",
        prompt_file="jan_sunwai_v3_system.txt",
    )
    meta = JanSunwaiV3MetaExtract(
        session_type="information",
        print_mode="info_sheet",
        chief_complaint_or_query="Nivas praman documents",
        department_tag="certificates",
    )
    with patch(
        "app.agent.llm.complete_structured",
        new_callable=AsyncMock,
        return_value=meta,
    ):
        with patch(
            "app.agent.llm.complete",
            new_callable=AsyncMock,
            return_value="आपका प्रश्न : निवास\nदिनांक: {{DATE}}",
        ):
            with patch(
                "app.kiosk.post_call_extract.next_complaint_number",
                new_callable=AsyncMock,
            ) as mock_num:
                with patch(
                    "app.kiosk.session_store.kiosk_session_store.update",
                    new_callable=AsyncMock,
                ):
                    out = await run_post_call_extract(session, centre)
    mock_num.assert_not_called()
    assert out.complaint_number is None
    assert out.grievance is not None
    assert out.grievance.print_mode == "info_sheet"
    assert out.grievance.print_document_text


@pytest.mark.asyncio
async def test_v3_mixed_session_prints_application_letter_only():
    session = KioskSession(
        centre_id="c1",
        phone="9876543210",
        language="hi",
        finish_print_mode="info_sheet",
        finish_session_type="mixed",
        transcript=[
            KioskTranscriptEntry(
                speaker="user",
                text="Bijli bill zyada hai aur nivas praman ke liye kya document chahiye",
            ),
        ],
    )
    centre = KioskCentre(
        slug="varanasi-jan-sunwai-v3",
        name="Varanasi Jan Sunwai v3",
        prompt_file="jan_sunwai_v3_system.txt",
        complaint_prefix="JS-VNS",
    )
    meta = JanSunwaiV3MetaExtract(
        full_name="Ram Kumar",
        session_type="mixed",
        print_mode="info_sheet",
        confirmed_summary="High electricity bill",
        chief_complaint_or_query="Nivas praman documents",
        department_tag="electricity",
        documents_to_attach_or_required=["Aadhaar", "Bill copy"],
    )
    letter_body = (
        "                 जन सुनवाई केंद्र\n"
        "दिनांक: {{DATE}}\n"
        "संलग्नक:\n1. Aadhaar\n2. Bill copy"
    )
    with patch(
        "app.agent.llm.complete_structured",
        new_callable=AsyncMock,
        return_value=meta,
    ):
        with patch(
            "app.agent.llm.complete",
            new_callable=AsyncMock,
            return_value=letter_body,
        ):
            with patch(
                "app.kiosk.post_call_extract.next_complaint_number",
                new_callable=AsyncMock,
                return_value="JS-VNS-20250825-00002",
            ):
                with patch(
                    "app.kiosk.session_store.kiosk_session_store.update",
                    new_callable=AsyncMock,
                ):
                    out = await run_post_call_extract(session, centre)
    assert out.status == "completed"
    assert out.grievance is not None
    assert out.grievance.print_mode == "application_letter"
    assert out.grievance.print_document_text
    assert "संलग्नक" in out.grievance.print_document_text
    assert "Bill copy" in out.grievance.print_document_text


@pytest.mark.asyncio
async def test_v3_template_fallback_when_llm_letter_empty():
    session = KioskSession(
        centre_id="c1",
        phone="9876543210",
        language="hi",
        finish_print_mode="application_letter",
        finish_session_type="complaint",
        transcript=[
            KioskTranscriptEntry(speaker="user", text="Ganda paani aa raha hai"),
        ],
    )
    centre = KioskCentre(
        slug="varanasi-jan-sunwai-v3",
        name="Varanasi Jan Sunwai v3",
        prompt_file="jan_sunwai_v3_system.txt",
    )
    meta = JanSunwaiV3MetaExtract(
        full_name="Ram Kumar",
        confirmed_summary="Ganda paani",
        department_tag="water",
    )
    with patch(
        "app.agent.llm.complete_structured",
        new_callable=AsyncMock,
        return_value=meta,
    ):
        with patch(
            "app.agent.llm.complete",
            new_callable=AsyncMock,
            return_value="",
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
    assert out.grievance is not None
    assert out.grievance.print_document_text
    assert "जन सुनवाई केंद्र" in out.grievance.print_document_text


@pytest.mark.asyncio
async def test_v3_partial_when_document_unavailable():
    session = KioskSession(
        centre_id="c1",
        phone="9876543210",
        language="hi",
        finish_print_mode="application_letter",
        finish_session_type="complaint",
        transcript=[
            KioskTranscriptEntry(speaker="user", text="Shikayat"),
        ],
    )
    centre = KioskCentre(
        slug="varanasi-jan-sunwai-v3",
        name="Varanasi Jan Sunwai v3",
        prompt_file="jan_sunwai_v3_system.txt",
    )
    meta = JanSunwaiV3MetaExtract(
        full_name="Ram Kumar",
        department_tag="water",
    )
    with patch(
        "app.agent.llm.complete_structured",
        new_callable=AsyncMock,
        return_value=meta,
    ):
        with patch(
            "app.agent.llm.complete",
            new_callable=AsyncMock,
            return_value="",
        ):
            with patch(
                "app.kiosk.post_call_extract.template_v3_print_document",
                return_value="",
            ):
                with patch(
                    "app.kiosk.session_store.kiosk_session_store.update",
                    new_callable=AsyncMock,
                ):
                    out = await run_post_call_extract(session, centre)
    assert out.status == "partial"
    assert out.complaint_number is None
