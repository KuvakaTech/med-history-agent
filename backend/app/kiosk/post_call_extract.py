"""Post-call grievance extraction for Jan Sunwai kiosk."""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field

from app.agent import llm
from app.kiosk.counter_store import next_complaint_number
from app.kiosk.models import (
    GrievanceAddress,
    GrievanceRecord,
    KioskSession,
    KioskTranscriptEntry,
)
from app.kiosk.session_store import kiosk_session_store

log = logging.getLogger(__name__)


class GrievanceExtract(BaseModel):
    full_name: Optional[str] = None
    father_guardian_name: Optional[str] = None
    age: Optional[int] = None
    is_senior_citizen: Optional[bool] = None
    is_divyang: Optional[bool] = None
    residential_house: Optional[str] = None
    residential_street: Optional[str] = None
    residential_village_mohalla: Optional[str] = None
    residential_gp_ward: Optional[str] = None
    residential_tehsil: Optional[str] = None
    residential_block: Optional[str] = None
    residential_post_office: Optional[str] = None
    residential_pin_code: Optional[str] = None
    residential_landmark: Optional[str] = None
    complaint_location_same_as_home: Optional[bool] = None
    complaint_house: Optional[str] = None
    complaint_street: Optional[str] = None
    complaint_village_mohalla: Optional[str] = None
    complaint_gp_ward: Optional[str] = None
    complaint_tehsil: Optional[str] = None
    complaint_block: Optional[str] = None
    complaint_post_office: Optional[str] = None
    complaint_pin_code: Optional[str] = None
    complaint_landmark: Optional[str] = None
    category: Optional[str] = None
    sub_category: Optional[str] = None
    verbatim_problem: Optional[str] = None
    confirmed_summary: Optional[str] = None
    since_when: Optional[str] = None
    affected_count: Optional[str] = None
    prior_action: Optional[str] = None
    desired_outcome: Optional[str] = None
    department_tag: Optional[str] = None
    urgency: Optional[str] = None
    sentiment: Optional[str] = None
    has_photos_or_docs: Optional[bool] = None
    optional_email: Optional[str] = None
    category_details: dict[str, Any] = Field(default_factory=dict)


_EXTRACT_PROMPT = """\
Extract a structured Jan Sunwai grievance record from this kiosk voice transcript.

Rules:
- Use ONLY what is explicitly said. Do not invent facts.
- Phone was captured at kiosk intake — do not extract phone from transcript.
- Never extract Aadhaar, bank account, OTP, or passwords.
- urgency: "urgent" for emergencies, safety threats, live electrical danger, rapidly worsening health; else "normal".
- department_tag: one of health, water, electricity, road, ration, land_revenue, pension_welfare,
  sanitation, education, police_safety, employment, other, to_be_assigned.

Transcript:
{transcript}
"""


def format_transcript(entries: list[KioskTranscriptEntry]) -> str:
    if not entries:
        return ""
    lines: list[str] = []
    for e in entries:
        speaker = "Citizen" if e.speaker == "user" else "Agent"
        text = (e.text or "").strip()
        if text:
            lines.append(f"{speaker}: {text}")
    return "\n".join(lines)


def _address_from_extract(prefix: str, data: GrievanceExtract) -> GrievanceAddress:
    return GrievanceAddress(
        house=getattr(data, f"{prefix}_house"),
        street=getattr(data, f"{prefix}_street"),
        village_mohalla=getattr(data, f"{prefix}_village_mohalla"),
        gp_ward=getattr(data, f"{prefix}_gp_ward"),
        tehsil=getattr(data, f"{prefix}_tehsil"),
        block=getattr(data, f"{prefix}_block"),
        post_office=getattr(data, f"{prefix}_post_office"),
        pin_code=getattr(data, f"{prefix}_pin_code"),
        landmark=getattr(data, f"{prefix}_landmark"),
    )


async def run_post_call_extract(session: KioskSession) -> KioskSession:
    transcript_text = format_transcript(session.transcript)
    if not transcript_text.strip():
        session.status = "partial"
        session.phase = "result"
        session.ended_at = datetime.utcnow()
        await kiosk_session_store.update(session)
        return session

    extracted = GrievanceExtract()
    try:
        extracted = await llm.complete_structured(  # type: ignore[assignment]
            _EXTRACT_PROMPT.format(transcript=transcript_text),
            GrievanceExtract,
            fast=False,
            max_tokens=4096,
        )
    except Exception as exc:
        log.error(
            "Kiosk post-call extract failed for %s: %s",
            session.session_id,
            exc,
            exc_info=True,
        )

    residential = _address_from_extract("residential", extracted)
    complaint_addr = None
    if not extracted.complaint_location_same_as_home:
        complaint_addr = _address_from_extract("complaint", extracted)

    session.grievance = GrievanceRecord(
        full_name=extracted.full_name,
        father_guardian_name=extracted.father_guardian_name,
        age=extracted.age,
        is_senior_citizen=extracted.is_senior_citizen,
        is_divyang=extracted.is_divyang,
        residential_address=residential,
        complaint_location_same_as_home=extracted.complaint_location_same_as_home,
        complaint_address=complaint_addr,
        category=extracted.category,
        sub_category=extracted.sub_category,
        verbatim_problem=extracted.verbatim_problem,
        confirmed_summary=extracted.confirmed_summary,
        since_when=extracted.since_when,
        affected_count=extracted.affected_count,
        prior_action=extracted.prior_action,
        desired_outcome=extracted.desired_outcome,
        department_tag=extracted.department_tag,
        urgency=extracted.urgency or "normal",
        sentiment=extracted.sentiment,
        has_photos_or_docs=extracted.has_photos_or_docs,
        optional_email=extracted.optional_email,
        category_details=extracted.category_details,
    )
    session.complaint_number = await next_complaint_number(session.centre_id)
    session.status = "completed"
    session.phase = "result"
    session.ended_at = datetime.utcnow()
    await kiosk_session_store.update(session)
    return session
