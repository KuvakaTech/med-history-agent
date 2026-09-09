"""Post-call grievance extraction for kiosk centres."""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from pydantic import BaseModel, Field

from app.agent import llm
from app.core.config import settings
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

_JANSUNWAI_RECORD_RE = re.compile(
    r"<<<JANSUNWAI_RECORD\s*(\{.*?\})\s*JANSUNWAI_RECORD>>>",
    re.DOTALL | re.IGNORECASE,
)


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


class JanSunwaiV3MetaExtract(GrievanceExtract):
    """Structured v3 metadata — print body generated in a separate LLM step."""

    session_type: Optional[str] = None
    print_mode: Optional[str] = None
    primary_intent: Optional[str] = None
    chief_complaint_or_query: Optional[str] = None
    narrative: Optional[str] = None
    addressed_to_officer: Optional[str] = None
    addressed_to_office: Optional[str] = None
    addressed_to_location: Optional[str] = None
    documents_to_attach_or_required: list[str] = Field(default_factory=list)
    out_of_scope: Optional[bool] = None
    flags: list[str] = Field(default_factory=list)
    not_captured: list[str] = Field(default_factory=list)


class JanSunwaiV3Extract(JanSunwaiV3MetaExtract):
    print_document_text: Optional[str] = None


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

_BARWANI_JAN_SUNWAI_EXTRACT_PROMPT = """\
Extract a structured Barwani Jan Sunwai district grievance record from this kiosk voice transcript.

Rules:
- Use ONLY what is explicitly said. Do not invent facts.
- Phone was captured at kiosk intake — do not extract phone from transcript.
- Never extract Aadhaar, bank account, OTP, or passwords.
- urgency: "urgent" for emergencies, safety threats, live electrical danger, land grab/threat,
  Narmada/punarvas distress, self-harm/distress, rapidly worsening health; else "normal".
- department_tag: one of health, water, electricity, road, ration, land_revenue, pension_welfare,
  sanitation, education, police_safety, employment, agriculture, certificates, out_of_scope,
  other, to_be_assigned.
- category_details (dict) — populate when mentioned:
  - tehsil, block: Barwani, Sendhwa, Pansemal, Warla/Varla, Niwali, Thikri/Thikari, Pati, Anjad, Rajpur
  - sub_division: Barwani or Sendhwa SDM
  - out_of_scope: true for RTI, civil sub-judice only matters, govt employee transfer, etc.
  - out_of_scope_reason: e.g. rti, sub_judice, govt_employee_service
  - route_to: e.g. MPPKVVCL, Tehsil, Nagar_Palika, PWD, DSO, CMHO, SP_Barwani, NVDA,
    Zila_Panchayat, Lok_Seva_Kendra, Janpad_Panchayat
  - revenue/land (9A): khasra, gata, khatauni, rakba, namantaran_type (purchase/inheritance),
    vaad_case_number, sub_judice (court matter), opposite_party
  - punarvas: true for Narmada/Sardar Sarovar rehabilitation matters; nvda_route if stated
  - billing (8.1): current_amount, previous_amount, consumer_number, connection_type
- out_of_scope matters → department_tag out_of_scope + category_details.out_of_scope=true + route_to.

Transcript:
{transcript}
"""

_JAN_SUNWAI_V3_META_EXTRACT_PROMPT = """\
Extract a structured Jan Sunwai v3 kiosk record from this voice transcript.

The kiosk has TWO outputs:
- COMPLAINT (session_type=complaint): print_mode MUST be application_letter.
- INFORMATION / HELP (session_type=information or help_desk): print_mode MUST be info_sheet
  unless nothing was provided — then info_sheet or none.
- MIXED: session_type=mixed; pick the dominant print_mode.

Rules:
- Use ONLY what is explicitly said. Do not invent facts, documents, officers, khasra, fees, or IDs.
- Do NOT generate the printable letter body here — only structured fields.
- Phone was captured at intake — do not extract phone from transcript.
- Never extract Aadhaar, bank account, OTP, or passwords.
- urgency: "urgent" for emergencies, safety threats, land grab/threat, self-harm; else "normal".
- department_tag: health, water, electricity, road, ration, land_revenue, pension_welfare,
  sanitation, education, police_safety, employment, agriculture, certificates, out_of_scope,
  other, to_be_assigned.
- addressed_to_officer, addressed_to_office, addressed_to_location: competent officer for Mode A
  letters (Section 12); null for pure info sheets.
- documents_to_attach_or_required: list from Section 11 that apply — only what was discussed.
- category_details: tehsil, block, ward, revenue/land fields, out_of_scope, route_to as before.

Transcript:
{transcript}
"""

_JAN_SUNWAI_V3_LETTER_PROMPT = """\
Write the FULL one-page A4 printable document for a Varanasi Jan Sunwai kiosk session.

Document type: {doc_kind}
Use शुद्ध सरकारी हिंदी for application_letter; simple clear Hindi for info_sheet.
Follow Section 13.2 (letter) or 13.3 (info sheet) skeleton from the Jan Sunwai spec.
Leave {{DATE}} and {{TIME}} as literal tokens — the system fills them later.
NEVER include any complaint number, reference ID, or tracking number.

Use ONLY facts from the structured record and transcript below. Do not invent khasra, fees,
officers, or documents not mentioned.

Structured record (JSON):
{record_json}

Transcript:
{transcript}

Output ONLY the printable document text. No JSON, no markdown fences, no commentary.
"""

_JAN_SUNWAI_V3_EXTRACT_PROMPT = _JAN_SUNWAI_V3_META_EXTRACT_PROMPT


def _extract_prompt_for_centre(centre: KioskCentre) -> str:
    key = prompt_file_for_centre(centre)
    if key == "jan_sunwai_v3_system.txt":
        return _JAN_SUNWAI_V3_EXTRACT_PROMPT
    if key == "nagar_nigam_system.txt":
        return _NAGAR_NIGAM_EXTRACT_PROMPT
    if key == "barwani_jan_sunwai":
        return _BARWANI_JAN_SUNWAI_EXTRACT_PROMPT
    return _JAN_SUNWAI_EXTRACT_PROMPT


def _is_v3_centre(centre: KioskCentre) -> bool:
    return prompt_file_for_centre(centre) == "jan_sunwai_v3_system.txt"


def _ist_now() -> datetime:
    return datetime.now(timezone.utc) + timedelta(hours=5, minutes=30)


def fill_print_placeholders(text: Optional[str]) -> Optional[str]:
    if not text:
        return text
    now = _ist_now()
    date_token = now.strftime("%d %B %Y")
    time_token = now.strftime("%H:%M")
    # Double braces first — `{DATE}` is a substring of `{{DATE}}`.
    filled = text.replace("{{DATE}}", date_token).replace("{{TIME}}", time_token)
    return filled.replace("{DATE}", date_token).replace("{TIME}", time_token)


def parse_jansunwai_record(transcript_text: str) -> Optional[dict[str, Any]]:
    match = _JANSUNWAI_RECORD_RE.search(transcript_text or "")
    if not match:
        return None
    raw = match.group(1).strip()
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else None
    except json.JSONDecodeError:
        log.debug("Failed to parse JANSUNWAI_RECORD JSON", exc_info=True)
        return None


def _addressed_to_from_record(data: dict[str, Any]) -> Optional[dict[str, str]]:
    addr = data.get("addressed_to")
    if isinstance(addr, dict):
        return {
            "officer": str(addr.get("officer") or ""),
            "office": str(addr.get("office") or ""),
            "location": str(addr.get("location") or ""),
        }
    officer = data.get("addressed_to_officer")
    if officer:
        return {
            "officer": str(officer),
            "office": str(data.get("addressed_to_office") or ""),
            "location": str(data.get("addressed_to_location") or "जनपद वाराणसी"),
        }
    return None


def _addressed_to_from_extract(extracted: JanSunwaiV3MetaExtract) -> Optional[dict[str, str]]:
    if not any(
        (
            extracted.addressed_to_officer,
            extracted.addressed_to_office,
            extracted.addressed_to_location,
        )
    ):
        return None
    return {
        "officer": extracted.addressed_to_officer or "",
        "office": extracted.addressed_to_office or "",
        "location": extracted.addressed_to_location or "जनपद वाराणसी",
    }


def _resolve_v3_modes(
    session: KioskSession,
    extracted: JanSunwaiV3MetaExtract,
    record: Optional[dict[str, Any]],
) -> tuple[str, str]:
    session_type = (
        (record or {}).get("session_type")
        or session.finish_session_type
        or extracted.session_type
        or "complaint"
    )
    print_mode = (
        (record or {}).get("print_mode")
        or session.finish_print_mode
        or extracted.print_mode
        or "application_letter"
    )
    session_type = str(session_type).strip().lower()
    print_mode = str(print_mode).strip().lower()
    if session_type in ("information", "help_desk") and print_mode == "application_letter":
        print_mode = "info_sheet"
    if print_mode not in ("application_letter", "info_sheet", "none"):
        print_mode = (
            "application_letter"
            if session_type in ("complaint", "mixed")
            else "info_sheet"
        )
    return session_type, print_mode


def _grievance_from_v3_extract(
    extracted: JanSunwaiV3MetaExtract,
    record: Optional[dict[str, Any]],
    session_type: str,
    print_mode: str,
    print_text: Optional[str],
) -> GrievanceRecord:
    addressed_to = _addressed_to_from_record(record or {}) or _addressed_to_from_extract(
        extracted
    )
    residential = _address_from_extract("residential", extracted)
    complaint_addr = None
    if not extracted.complaint_location_same_as_home:
        complaint_addr = _address_from_extract("complaint", extracted)

    summary = (
        extracted.confirmed_summary
        or extracted.verbatim_problem
        or extracted.chief_complaint_or_query
        or extracted.narrative
    )
    docs = extracted.documents_to_attach_or_required
    if not docs and record:
        docs = record.get("documents_to_attach_or_required") or []
    flags = extracted.flags
    if not flags and record:
        flags = record.get("flags") or []
    not_captured = extracted.not_captured
    if not not_captured and record:
        not_captured = record.get("not_captured") or []

    out_of_scope = extracted.out_of_scope
    if out_of_scope is None and record:
        out_of_scope = record.get("out_of_scope")

    return GrievanceRecord(
        session_type=session_type,
        print_mode=print_mode,
        print_document_text=print_text,
        primary_intent=extracted.primary_intent
        or (record or {}).get("primary_intent"),
        addressed_to=addressed_to,
        documents_to_attach_or_required=list(docs or []),
        out_of_scope=out_of_scope,
        flags=list(flags or []),
        not_captured=list(not_captured or []),
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
        verbatim_problem=extracted.verbatim_problem or extracted.narrative,
        confirmed_summary=summary,
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


_DEPARTMENT_HINDI: dict[str, str] = {
    "health": "स्वास्थ्य",
    "water": "जल / पेयजल",
    "electricity": "विद्युत",
    "road": "सड़क / PWD",
    "ration": "खाद्य / राशन",
    "land_revenue": "राजस्व / भूमि",
    "pension_welfare": "पension / कल्याण",
    "sanitation": "सफाई / स्वच्छता",
    "education": "शिक्षा",
    "police_safety": "पुलिस / सुरक्षा",
    "employment": "रोजगार",
    "agriculture": "कृषि",
    "certificates": "प्रमाण पत्र",
    "out_of_scope": "अन्य / बाह्य",
    "other": "अन्य",
    "to_be_assigned": "निर्धारित होना शेष",
}


def _department_hindi(tag: Optional[str]) -> str:
    if not tag:
        return "_______________"
    return _DEPARTMENT_HINDI.get(str(tag).strip().lower(), str(tag))


def _format_residential_line(extracted: GrievanceExtract) -> str:
    parts = [
        extracted.residential_house,
        extracted.residential_street,
        extracted.residential_village_mohalla,
        extracted.residential_gp_ward,
        extracted.residential_tehsil,
        extracted.residential_block,
        extracted.residential_post_office,
        extracted.residential_pin_code,
        extracted.residential_landmark,
    ]
    line = ", ".join(str(p).strip() for p in parts if p and str(p).strip())
    return line or "_______________"


def _blank_line(value: Optional[str], placeholder: str = "_______________") -> str:
    text = (value or "").strip()
    return text if text else placeholder


def _numbered_lines(items: list[str], prefix: str) -> str:
    if not items:
        return f"        1. {prefix}"
    return "\n".join(f"        {i + 1}. {item}" for i, item in enumerate(items))


def _needs_printable_document(print_mode: str) -> bool:
    return print_mode in ("application_letter", "info_sheet")


def template_v3_print_document(
    extracted: JanSunwaiV3MetaExtract,
    print_mode: str,
) -> str:
    """Deterministic Section 13.2 / 13.3 fallback when LLM document generation fails."""
    if print_mode == "info_sheet":
        return _template_info_sheet(extracted)
    return _template_application_letter(extracted)


def _template_application_letter(extracted: JanSunwaiV3MetaExtract) -> str:
    name = _blank_line(extracted.full_name)
    father = _blank_line(extracted.father_guardian_name)
    address = _format_residential_line(extracted)
    officer = _blank_line(extracted.addressed_to_officer, "संबंधित अधिकारी")
    office = _blank_line(extracted.addressed_to_office, "संबंधित कार्यालय")
    location = _blank_line(extracted.addressed_to_location, "जनपद वाराणसी")
    subject = (
        extracted.confirmed_summary
        or extracted.chief_complaint_or_query
        or extracted.verbatim_problem
        or extracted.narrative
        or "शिकायत के संबंध में"
    )
    facts = (
        extracted.narrative
        or extracted.verbatim_problem
        or extracted.confirmed_summary
        or extracted.chief_complaint_or_query
        or "_______________"
    )
    prayer = extracted.desired_outcome or "संबंधित विभाग से उचित कार्यवाही की जाए।"
    docs = extracted.documents_to_attach_or_required or ["संबंधित दस्तावेज़"]
    dept = _department_hindi(extracted.department_tag)
    attachments = _numbered_lines(list(docs), "संबंधित दस्तावेज़")
    return f"""                 जन सुनवाई केंद्र, जनपद वाराणसी
      दिनांक: {{{{DATE}}}}        समय: {{{{TIME}}}}
      विभाग: {dept}     प्रकृति: शिकायत / प्रार्थना पत्र

सेवा में,
        श्रीमान {officer} महोदय,
        {office}, {location}।

विषय : {subject}।

महोदय,
        सविनय निवेदन है कि मैं {name}, पुत्र/पुत्री श्री {father},
निवासी {address}, जनपद वाराणसी का निवासी/निवासी हूँ। {facts}

        अतः महोदय से सविनय निवेदन है कि {prayer}

                                              प्रार्थी,
                                              नाम : {name}
                                              पिता/पति : {father}
                                              पता : {address}
                                              हस्ताक्षर : ...........................

संलग्नक (साथ लगाए जाने वाले दस्तावेज़) :
{attachments}"""


def _template_info_sheet(extracted: JanSunwaiV3MetaExtract) -> str:
    name = _blank_line(extracted.full_name, "")
    question = (
        extracted.chief_complaint_or_query
        or extracted.confirmed_summary
        or extracted.verbatim_problem
        or extracted.narrative
        or "_______________"
    )
    answer = (
        extracted.desired_outcome
        or extracted.narrative
        or extracted.confirmed_summary
        or "कृपया संबंधित कार्यालय में संपर्क करें।"
    )
    docs = extracted.documents_to_attach_or_required or ["पहचान पत्र", "संबंधित आवेदन/प्रपत्र"]
    route = (
        extracted.addressed_to_office
        or (extracted.category_details or {}).get("route_to")
        or "संबंधित तहसील / जन सुनवाई काउंटर"
    )
    dept = _department_hindi(extracted.department_tag)
    name_line = f"      नाम: {name}          " if name else "      "
    doc_lines = _numbered_lines(list(docs), "संबंधित दस्तावेज़")
    return f"""                 जन सुनवाई केंद्र, जनपद वाराणसी
      दिनांक: {{{{DATE}}}}        समय: {{{{TIME}}}}
{name_line}विषय-क्षेत्र: {dept}

आपका प्रश्न : {question}

संक्षिप्त उत्तर : {answer}

आवश्यक दस्तावेज़ / प्रक्रिया :
{doc_lines}

कहाँ जाएँ / कैसे करें : {route}

नोट : शुल्क/समय-सीमा काउंटर पर पुष्टि कर लीजिए।"""


async def _generate_v3_print_document_llm(
    extracted: JanSunwaiV3MetaExtract,
    transcript_text: str,
    print_mode: str,
) -> Optional[str]:
    doc_kind = (
        "application_letter (प्रार्थना पत्र / Section 13.2)"
        if print_mode == "application_letter"
        else "info_sheet (जानकारी पत्र / Section 13.3)"
    )
    prompt = _JAN_SUNWAI_V3_LETTER_PROMPT.format(
        doc_kind=doc_kind,
        record_json=json.dumps(
            extracted.model_dump(mode="json", exclude_none=True),
            ensure_ascii=False,
            indent=2,
        ),
        transcript=transcript_text,
    )
    try:
        text = await llm.complete(
            prompt,
            fast=False,
            max_tokens=8192,
            provider="anthropic",
            model=settings.KIOSK_POST_CALL_MODEL or None,
        )
        cleaned = (text or "").strip()
        return cleaned or None
    except Exception as exc:
        log.warning(
            "Kiosk v3 print document LLM failed: %s",
            exc,
            exc_info=True,
        )
        return None


async def _run_v3_post_call_extract(
    session: KioskSession,
    centre: KioskCentre,
    transcript_text: str,
) -> KioskSession:
    record = parse_jansunwai_record(transcript_text)
    extracted = JanSunwaiV3MetaExtract()
    try:
        extracted = await llm.complete_structured(  # type: ignore[assignment]
            _JAN_SUNWAI_V3_META_EXTRACT_PROMPT.format(transcript=transcript_text),
            JanSunwaiV3MetaExtract,
            fast=False,
            max_tokens=4096,
            provider="anthropic",
            model=settings.KIOSK_POST_CALL_MODEL or None,
        )
    except Exception as exc:
        log.error(
            "Kiosk v3 post-call meta extract failed for %s: %s",
            session.session_id,
            exc,
            exc_info=True,
        )

    session_type, print_mode = _resolve_v3_modes(session, extracted, record)
    print_text: Optional[str] = None
    if record and record.get("print_document_text"):
        print_text = str(record["print_document_text"])

    if _needs_printable_document(print_mode) and not (print_text or "").strip():
        print_text = await _generate_v3_print_document_llm(
            extracted, transcript_text, print_mode
        )

    if _needs_printable_document(print_mode) and not (print_text or "").strip():
        print_text = template_v3_print_document(extracted, print_mode)

    print_text = fill_print_placeholders(print_text)

    session.grievance = _grievance_from_v3_extract(
        extracted,
        record,
        session_type,
        print_mode,
        print_text,
    )

    if _needs_printable_document(print_mode) and not (print_text or "").strip():
        session.status = "partial"
    else:
        session.status = "completed"

    if print_mode == "application_letter" and session.status == "completed":
        session.complaint_number = await next_complaint_number(
            session.centre_id,
            prefix=complaint_prefix_for_centre(centre),
        )
    else:
        session.complaint_number = None

    session.phase = "result"
    session.ended_at = datetime.utcnow()
    await kiosk_session_store.update(session)
    return session


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

    if _is_v3_centre(centre):
        return await _run_v3_post_call_extract(session, centre, transcript_text)

    prompt_template = _extract_prompt_for_centre(centre)
    extracted = GrievanceExtract()
    try:
        extracted = await llm.complete_structured(  # type: ignore[assignment]
            prompt_template.format(transcript=transcript_text),
            GrievanceExtract,
            fast=False,
            max_tokens=4096,
            provider="anthropic",
            model=settings.KIOSK_POST_CALL_MODEL or None,
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
