"""Post-call structured extraction for ticketing voice V2.

Runs only after the Gemini Live conversation ends. Claude (via llm.complete_structured)
rebuilds name/age/category/flags/qa_log from the raw transcript; SOAP comes from
SummarizationService. Live red-flag events are intentionally not emitted during V2 calls.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field

from app.agent import llm
from app.agent.summarization.service import SummarizationService
from app.ticketing.models import (
    CategoryInfo,
    TicketFlag,
    TicketQAEntry,
    TicketSession,
    TicketTranscriptEntry,
)
from app.ticketing.patient_store import ticket_patient_store
from app.ticketing.session_store import ticket_session_store
from app.ticketing.triage_engine import TriageMeta

log = logging.getLogger(__name__)


class ExtractedQA(BaseModel):
    question: str
    answer: str


class ExtractedFlag(BaseModel):
    flag_type: str
    description: str


class PostCallExtract(BaseModel):
    patient_name: Optional[str] = None
    patient_age: Optional[int] = None
    category_key: Optional[str] = None
    category_label: Optional[str] = None
    qa_log: list[ExtractedQA] = Field(default_factory=list)
    flags: list[ExtractedFlag] = Field(default_factory=list)


_EXTRACT_PROMPT = """\
Extract a structured clinical intake record from this hospital check-in voice transcript.

Rules:
- Use ONLY what is explicitly said. Do not invent symptoms, names, ages, or departments.
- patient_name: string if clearly shared, null if declined or never given.
- patient_age: integer years if stated, else null.
- category_key: one of the allowed keys below that best fits the reason for visit, or null.
- category_label: matching human-readable label, or null.
- qa_log: reconstruct agent questions and patient answers as pairs, in order. Skip empty turns.
- flags: clinical red flags only (CRITICAL_RED_FLAG, RED_FLAG, IMPORTANT, NOTE) with a short description.
  CRITICAL_RED_FLAG: chest pain, severe breathlessness, worst-ever headache, stroke signs,
  vomiting blood / black stools, loss of consciousness, allergic swelling with breathing trouble,
  active suicidal intent, high fever with confusion or stiff neck.
  RED_FLAG: unexplained weight loss, prolonged fever/night sweats, blood in urine/stool/cough,
  pain to left arm/jaw, syncope, new lumps, rapidly worsening neuro symptoms, pain ≥8/10.

Allowed category keys: {category_keys}

Transcript:
{transcript}
"""

_TRIAGE_FALLBACK_PROMPT = """\
This is a short hospital-reception transcript (name, age, reason for visit).

Extract:
  patient_name, patient_age, category_guess (one of the allowed keys or null),
  category_label, category_confidence (high/low/none), is_complete, new_flags.

Allowed category keys: {category_keys}

Transcript:
{transcript}

Return JSON only.
"""


def format_transcript(entries: list[TicketTranscriptEntry]) -> str:
    if not entries:
        return ""
    lines: list[str] = []
    for e in entries:
        speaker = "Patient" if e.speaker == "user" else "Agent"
        text = (e.text or "").strip()
        if text:
            lines.append(f"{speaker}: {text}")
    return "\n".join(lines)


async def extract_triage_fallback(
    transcript: str,
    category_keys: str,
) -> TriageMeta:
    """Haiku extract used when finish_triage never fires. Escape hatch only."""
    if not transcript.strip():
        return TriageMeta()
    try:
        result = await llm.complete_structured(
            _TRIAGE_FALLBACK_PROMPT.format(
                category_keys=category_keys,
                transcript=transcript,
            ),
            TriageMeta,
            fast=True,
        )
        return result  # type: ignore[return-value]
    except Exception as exc:
        log.warning("Triage fallback extract failed: %s", exc)
        return TriageMeta()


async def run_post_call_extract(
    session: TicketSession,
    categories: list,
) -> TicketSession:
    """Fill session.qa_log / flags / summary / status from the raw transcript.

    Empty transcript → status=partial, no LLM call.
    """
    transcript_text = format_transcript(session.transcript)
    if not transcript_text.strip():
        session.status = "partial"
        session.ended_at = datetime.utcnow()
        session.phase = "result"
        await ticket_session_store.update(session)
        return session

    keys = ", ".join(f'"{c.key}"' for c in categories)
    extracted = PostCallExtract()
    try:
        extracted = await llm.complete_structured(  # type: ignore[assignment]
            _EXTRACT_PROMPT.format(category_keys=keys, transcript=transcript_text),
            PostCallExtract,
            fast=False,
            max_tokens=2048,
        )
    except Exception as exc:
        log.error(
            "Post-call extract failed for session %s: %s",
            session.session_id,
            exc,
            exc_info=True,
        )

    valid = {c.key: c.label for c in categories}
    if (
        extracted.category_key
        and extracted.category_key in valid
        and session.category is None
    ):
        session.category = CategoryInfo(
            key=extracted.category_key,
            label=extracted.category_label or valid[extracted.category_key],
            source="auto",
        )

    session.qa_log = [
        TicketQAEntry(
            question_id=f"v2_{i + 1}",
            question_text=pair.question,
            answer=pair.answer,
        )
        for i, pair in enumerate(extracted.qa_log)
        if pair.question or pair.answer
    ]
    session.turn_count = len(session.qa_log)
    session.flags = [
        TicketFlag(flag_type=f.flag_type or "NOTE", description=f.description or "")
        for f in extracted.flags
        if f.description
    ]

    try:
        soap = await SummarizationService().summarize(transcript_text)
        session.summary = soap
    except Exception as exc:
        log.error(
            "SOAP summarization failed for ticket session %s: %s",
            session.session_id,
            exc,
            exc_info=True,
        )
        session.summary = None

    session.status = "completed"
    session.phase = "result"
    session.ended_at = datetime.utcnow()
    await ticket_session_store.update(session)

    name = extracted.patient_name
    if name in ("declined", "the patient", ""):
        name = None
    age = extracted.patient_age
    try:
        patient = await ticket_patient_store.get(session.patient_id)
        if patient is not None:
            if name:
                patient.name = name
            if age is not None:
                patient.age = age
            if session.gender and session.gender != "unknown":
                patient.gender = session.gender
            await ticket_patient_store.update(patient)
    except Exception as exc:
        log.warning("Patient persist after extract failed: %s", exc)

    return session
