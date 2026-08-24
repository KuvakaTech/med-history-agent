"""Consultation engine -- Phase 2 of the ticketing flow (questions 4-10).

Thin wrapper around the existing LLMHistoryEngine pattern, adapted for:
- TicketSession instead of ConsultationContext
- Category-aware system prompt
- Red-flags accumulated; NO diagnosis, completeness, or prescription calls

Key improvements over v1:
- Chief complaint may already be partially known from triage -- passed in and
  injected into context so Phase 2 never redundantly re-asks it.
- Question prompt tells the LLM what is already covered so it can ask natural
  follow-up questions instead of mechanically jumping topic-to-topic.
- Early-exit: if meta marks is_complete=true before MAX turns, we respect it
  (subject to MIN_CONSULTATION_TURNS floor).
- Urgency note is shown in question prompt, not just meta prompt.
"""
from __future__ import annotations

import asyncio
import logging
from typing import AsyncGenerator, Optional, Union

from pydantic import BaseModel

from app.agent import llm
from app.ticketing.models import TicketFlag, TicketQAEntry, TicketSession

log = logging.getLogger(__name__)

MIN_CONSULTATION_TURNS = 3   # ask at least 3 questions in phase 2
MAX_CONSULTATION_TURNS = 7   # questions 4-10 = up to 7 questions in phase 2


# --------------------------------------------------------------------------- #
# Prompts
# --------------------------------------------------------------------------- #

_CONSULT_SYSTEM = """\
You are a clinical AI screener conducting a pre-visit history intake at a hospital.
The patient is about to see a {category} doctor.

Your job: gather enough background so the doctor can use their consultation time well.
Ask ONE focused question per turn. Target {min_turns}-{max_turns} questions total.

What you already know from intake:
  Name    : {name}
  Age     : {age}
  Gender  : {gender}
  Dept    : {category}

REQUIRED AREAS to cover (roughly in this order, but adapt based on the conversation):
  1. chief_complaint    -- main symptom or concern (may already be known from triage)
  2. duration           -- when did it start and for how long?
  3. severity           -- how bad on a scale of 1-10?
  4. character_location -- what does it feel like and exactly where?
  5. modifying_factors  -- what makes it better or worse?
  6. associated_symptoms-- anything else alongside the main complaint?
  7. past_history       -- relevant past history, current medications, known allergies

RULES:
- ONE question per turn. ONE topic only.
- Do NOT re-ask anything already known (see covered areas passed in each turn).
- Follow up naturally on what the patient just said before jumping to the next area.
- Never diagnose, prescribe, or suggest treatments.
- Flag red flags immediately (chest pain, stroke symptoms, suicidal ideation, etc.).
- Respond in the patient's language: {language}.
- Do NOT ask about name, age, gender, or department -- you already know these.
"""

_CONSULT_Q_PROMPT = """\
Clinical history -- turn {turn} of max {max_turns}.

Conversation so far:
{history}

Patient just said: "{answer}"

Already covered areas: {covered_str}
Already known chief complaint from triage: {known_complaint}

{urgency_note}

Next area to explore: {next_area}

Generate the NEXT clinical question.
- If the patient's last answer already partially addresses "{next_area}", ask a natural
  follow-up on THAT rather than switching to a generic new-topic question.
- ONE topic only, in {language}.
- Output ONLY the question text. No JSON. No labels."""

_CONSULT_META_PROMPT = """\
Clinical history -- turn {turn} of max {max_turns}.

Conversation so far:
{history}

Patient just said: "{answer}"

Assess:
  is_complete    : true when all required areas are adequately covered,
                   OR turn >= {max_turns}. Respect min {min_turns} turns.
  new_flags      : list of NEW red flags from the latest answer only
                   (use flag_type + description keys).
  covered_areas  : list of area keys from {area_keys} that are NOW covered
                   (include all previously covered ones too).

Return JSON only -- no explanation, no markdown."""

_AREA_KEYS = [
    "chief_complaint",
    "duration",
    "severity",
    "character_location",
    "modifying_factors",
    "associated_symptoms",
    "past_history",
]

_AREA_PROMPTS = {
    "chief_complaint":     "chief complaint -- what is the main symptom or reason for the visit?",
    "duration":            "duration -- when did it start and how long has it been going on?",
    "severity":            "severity -- how bad is it on a scale of 1-10?",
    "character_location":  "character and location -- what does it feel like and exactly where?",
    "modifying_factors":   "modifying factors -- what makes it better or worse?",
    "associated_symptoms": "associated symptoms -- anything else alongside the main complaint?",
    "past_history":        "past medical history, current medications, and known allergies",
}


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #

class ConsultMeta(BaseModel):
    is_complete: bool = False
    new_flags: list[dict] = []
    covered_areas: list[str] = []


def _build_history(qa_log: list[TicketQAEntry]) -> str:
    if not qa_log:
        return "(none yet)"
    return "\n".join(
        f"  Agent  : {e.question_text}\n  Patient: {e.answer}" for e in qa_log
    )


def _urgency_note(turn: int) -> str:
    if turn >= MAX_CONSULTATION_TURNS - 1:
        return (
            f"IMPORTANT: Turn {turn}/{MAX_CONSULTATION_TURNS}. This is the LAST allowed question. "
            "Ask about the single most important remaining gap. After this, is_complete = true."
        )
    if turn >= MIN_CONSULTATION_TURNS:
        return (
            f"Note: Turn {turn}/{MAX_CONSULTATION_TURNS}. "
            "If all required areas are adequately covered, you may set is_complete = true."
        )
    return ""


def _next_area(covered: list[str]) -> str:
    for key in _AREA_KEYS:
        if key not in covered:
            return _AREA_PROMPTS[key]
    return "any remaining relevant clinical detail"


def _covered_str(covered: list[str]) -> str:
    if not covered:
        return "none yet"
    return ", ".join(covered)


# --------------------------------------------------------------------------- #
# Engine
# --------------------------------------------------------------------------- #

class ConsultationEngine:
    def __init__(
        self,
        category_label: str,
        language: str = "hi",
        name: str = "the patient",
        age: str = "unknown",
        gender: str = "unknown",
    ) -> None:
        from app.ticketing.triage_engine import _language_name
        self._lang_name = _language_name(language)
        self._system = _CONSULT_SYSTEM.format(
            category=category_label,
            min_turns=MIN_CONSULTATION_TURNS,
            max_turns=MAX_CONSULTATION_TURNS,
            language=self._lang_name,
            name=name,
            age=age,
            gender=gender,
        )

    async def opening_question(
        self,
        covered: list[str],
        known_complaint: Optional[str] = None,
    ) -> str:
        """First question for phase 2 -- no answer to process yet."""
        next_area = _next_area(covered)
        complaint_ctx = (
            f'The patient mentioned "{known_complaint}" during triage. '
            "Do NOT ask what they are here for again -- that is already known. "
            "Instead, start by asking a follow-up that deepens understanding of their complaint."
            if known_complaint
            else f"Ask about: {next_area}."
        )
        prompt = (
            f"The triage intake is complete. Now begin the clinical history.\n"
            f"{complaint_ctx}\n"
            f"ONE question, in {self._lang_name}. Output ONLY the question text."
        )
        return await llm.complete(prompt, system=self._system, fast=True)

    async def next_turn_stream(
        self,
        session: TicketSession,
        latest_answer: str,
        covered: list[str],
        known_complaint: Optional[str] = None,
    ) -> AsyncGenerator[Union[str, dict], None]:
        turn_count = len(session.qa_log)
        history = _build_history(session.qa_log)
        area_keys_str = ", ".join(f'"{k}"' for k in _AREA_KEYS)
        next_area = _next_area(covered)

        if turn_count >= MAX_CONSULTATION_TURNS:
            yield {
                "__done__": True,
                "is_complete": True,
                "question_text": "",
                "new_flags": [],
                "covered_areas": list(covered),
            }
            return

        q_prompt = _CONSULT_Q_PROMPT.format(
            turn=turn_count,
            max_turns=MAX_CONSULTATION_TURNS,
            history=history,
            answer=latest_answer,
            covered_str=_covered_str(covered),
            known_complaint=known_complaint or "not specified",
            urgency_note=_urgency_note(turn_count),
            next_area=next_area,
            language=self._lang_name,
        )
        m_prompt = _CONSULT_META_PROMPT.format(
            turn=turn_count,
            max_turns=MAX_CONSULTATION_TURNS,
            min_turns=MIN_CONSULTATION_TURNS,
            history=history,
            answer=latest_answer,
            area_keys=area_keys_str,
        )

        meta_task: asyncio.Task = asyncio.create_task(
            llm.complete_structured(m_prompt, ConsultMeta, system=self._system, fast=True)
        )

        question_text = ""
        try:
            async for token in llm.stream_complete(q_prompt, system=self._system, fast=True):
                question_text += token
                yield token
        except Exception as exc:
            log.error("ConsultationEngine stream failed: %s", exc)
            meta_task.cancel()
            raise

        try:
            meta: ConsultMeta = await meta_task  # type: ignore[assignment]
        except Exception as exc:
            log.warning("ConsultationEngine meta failed: %s", exc)
            meta = ConsultMeta()

        # Enforce minimum turns floor
        if turn_count < MIN_CONSULTATION_TURNS:
            meta.is_complete = False

        flags: list[TicketFlag] = []
        for fp in meta.new_flags:
            flag = TicketFlag(
                flag_type=fp.get("flag_type", "NOTE"),
                description=fp.get("description", ""),
            )
            session.flags.append(flag)
            flags.append(flag)

        # Merge covered areas: keep anything previously covered plus what meta says
        merged_covered = list(set(covered) | set(
            a for a in meta.covered_areas if a in _AREA_KEYS
        ))

        yield {
            "__done__": True,
            "is_complete": meta.is_complete,
            "question_text": question_text.strip(),
            "new_flags": [f.model_dump(mode="json") for f in flags],
            "covered_areas": merged_covered,
        }
