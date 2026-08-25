"""Post-call grievance extraction for kiosk centres."""
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
    KioskCentre,
    KioskSession,
    KioskTranscriptEntry,
    complaint_prefix_for_centre,
    prompt_file_for_centre,
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


_JAN_SUNWAI_EXTRACT_PROMPT = """\
Extract a structured Jan Sunwai district grievance record from this kiosk voice transcript.

Rules:
- Use ONLY what is explicitly said. Do not invent facts.
- Phone was captured at kiosk intake — do not extract phone from transcript.
- Never extract Aadhaar, bank account, OTP, or passwords.
- urgency: "urgent" for emergencies, safety threats, live electrical danger, land grab/threat,
  self-harm/distress, rapidly worsening health; else "normal".
- department_tag: one of health, water, electricity, road, ration, land_revenue, pension_welfare,
  sanitation, education, police_safety, employment, agriculture, certificates, out_of_scope,
  other, to_be_assigned.
- category_details (dict) — populate when mentioned:
  - tehsil, block, ward: Sadar, Pindra, Rajatalab; blocks Arajiline, Baragaon, etc.
  - out_of_scope: true for RTI, civil sub-judice only matters, govt employee transfer, etc.
  - out_of_scope_reason: e.g. rti, sub_judice, govt_employee_service
  - route_to: e.g. PVVNL, Tehsil, Nagar_Nigam, PWD, DSO, CMO, DRDA, Police
  - revenue/land (9A): khasra, gata, khatauni, rakba, namantaran_type (purchase/inheritance),
    vaad_case_number, sub_judice (court matter), opposite_party
  - billing (8.1): current_amount, previous_amount, consumer_number, connection_type
- out_of_scope matters → department_tag out_of_scope + category_details.out_of_scope=true + route_to.

Transcript:
{transcript}
"""

_NAGAR_NIGAM_EXTRACT_PROMPT = """\
Extract a structured Nagar Nigam civic complaint or service-intake record from this kiosk voice transcript.

Rules:
- Use ONLY what is explicitly said. Do not invent facts.
- Phone was captured at kiosk intake — do not extract phone from transcript.
- Never extract Aadhaar, bank account, OTP, or passwords.
- urgency: "urgent" for open manhole, sewage in homes, contaminated water illness, animal bite/attack,
  dangerous tree/pole, live electrical danger, disease outbreak, disconnection notice, overflow into homes,
  life/safety threats; else "normal".
- sentiment: use "bereaved" for death registration/certificate flows (6C); else omit or use stated tone.
- department_tag: one of sanitation, sewer_drainage, jal_kal_water, roads, street_lights,
  property_tax, stray_animals, encroachment, parks, birth_death_cert, public_health,
  out_of_scope, other, to_be_assigned.
- category_details (dict) — populate when mentioned:
  - zone_tag: Adampur, Bhelupur, Dashashwamedh, Kotwali, Varunapar, or ward number
  - out_of_scope: true if PVVNL bijli bill/supply, tehsil land dispute, private boundary, ration/pension, VDA map
  - out_of_scope_reason: e.g. pvvnl_electricity_bill, tehsil_land_dispute, private_land_boundary, ration, vda_map
  - route_to: e.g. PVVNL, Tehsil, Jan_Sunwai, VDA
  - service_request: true for birth/death registration intake (6B/6C), not a grievance
  - request_type: new_registration | certificate | correction | grievance
  - current_amount, previous_amount: for bill/tax disputes
  - consumer_number, connection_type: domestic | commercial | agricultural for bijli/water
  - nuisance_type: pigs | dogs | cattle | mosquitoes | drain (for 6G animal/public-health)
  - encroachment_on: public_road | footpath | drain | private_land
  - child_name, date_of_birth, place_of_birth, father_name, mother_name, informant_relation, days_since_event (birth 6B)
  - deceased_name, date_of_death, place_of_death, cause_of_death, informant_relation (death 6C)
- out_of_scope matters → department_tag out_of_scope + category_details.out_of_scope=true + route_to.

Transcript:
{transcript}
"""


def _extract_prompt_for_centre(centre: KioskCentre) -> str:
    if prompt_file_for_centre(centre) == "nagar_nigam_system.txt":
        return _NAGAR_NIGAM_EXTRACT_PROMPT
    return _JAN_SUNWAI_EXTRACT_PROMPT


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


async def run_post_call_extract(
    session: KioskSession,
    centre: KioskCentre,
) -> KioskSession:
    transcript_text = format_transcript(session.transcript)
    if not transcript_text.strip():
        session.status = "partial"
        session.phase = "result"
        session.ended_at = datetime.utcnow()
        await kiosk_session_store.update(session)
        return session

    prompt_template = _extract_prompt_for_centre(centre)
    extracted = GrievanceExtract()
    try:
        extracted = await llm.complete_structured(  # type: ignore[assignment]
            prompt_template.format(transcript=transcript_text),
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
    session.complaint_number = await next_complaint_number(
        session.centre_id,
        prefix=complaint_prefix_for_centre(centre),
    )
    session.status = "completed"
    session.phase = "result"
    session.ended_at = datetime.utcnow()
    await kiosk_session_store.update(session)
    return session
