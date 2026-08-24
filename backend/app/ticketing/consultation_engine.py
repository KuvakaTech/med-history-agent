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
from app.ticketing.triage_engine import _language_name

log = logging.getLogger(__name__)

MIN_CONSULTATION_TURNS = 7   # ask at least 7 questions in phase 2 for proper notes
MAX_CONSULTATION_TURNS = 12  # can go up to 12 total questions (3 triage + 12 consultation = 15 max)


# --------------------------------------------------------------------------- #
# Prompts
# --------------------------------------------------------------------------- #

_CONSULT_SYSTEM = """\
You are a junior clinical screener — a medical AI assistant performing pre-consultation history taking BEFORE the patient meets the {category} physician.

──────────────────────────────────────
ROLE & GOAL
──────────────────────────────────────
You are NOT replacing the doctor. Your job: gather complete essential clinical history so the physician can make the most of their consultation time.

GOAL: Cover ALL required areas by asking ONE focused question at a time. Each question should address a single topic only. The screening takes {min_turns}–{max_turns} questions and must NEVER exceed {max_turns}. Mark is_complete = true only when all areas are sufficiently covered.

Patient details already known:
  Name: {name}, Age: {age}, Gender: {gender}, Department: {category}

──────────────────────────────────────
8 REQUIRED AREAS — all must be covered before you mark is_complete = true
──────────────────────────────────────
1. Chief complaint — what brings them in today (may already be known from triage)
2. Timeline — when it started, how long it has been going on
3. Severity — how bad it is (1–10 scale where 10 = unbearable)
4. Character + location — what it feels like, where exactly
5. Modifying factors — what makes it better or worse
6. Associated symptoms — anything else they have noticed alongside it
7. Past medical/surgical history — prior conditions, operations, hospitalizations
8. Current medications and known allergies — what they take, any drug reactions

──────────────────────────────────────
QUESTIONING RULES — CRITICAL
──────────────────────────────────────
• Ask ONE question per turn. ONE topic only. Never bundle multiple questions into one.
• WRONG: "How long have you had this, how severe is it, and does anything make it better?"
• RIGHT: "How long have you been experiencing this?" → wait for answer → "On a scale of 1–10, how would you rate the severity?" → wait → "Is there anything that makes it better or worse?"
• Each question must be short, clear, and focused on a single piece of information.
• NEVER repeat a question you have already asked — check the CONSULTATION HISTORY carefully.
• Follow up naturally based on what the patient just said before moving to the next area.
• Never diagnose. Never suggest treatments or tests. The physician will handle examination.

──────────────────────────────────────
BEHAVIOUR RULES
──────────────────────────────────────
• Warm, calm, professional tone. Use plain accessible language.
• One question. One topic. Every single time.
• Build naturally on previous answers — show you're listening.
• Mark is_complete = true only after all required areas are sufficiently covered.
• Always respond in the patient's language: {language}.

──────────────────────────────────────
RED FLAG DETECTION — check EVERY answer for urgent symptoms
──────────────────────────────────────
CRITICAL_RED_FLAG (immediate medical attention):
  • Chest pain/tightness (possible heart attack)
  • Acute severe breathlessness or difficulty breathing
  • Sudden severe headache ("worst headache of my life")
  • Stroke symptoms: facial droop, arm weakness, slurred speech, confusion
  • Vomiting blood or black/tarry stools
  • Loss of consciousness or fainting
  • Signs of allergic reaction: swelling, difficulty breathing, rash
  • Active suicidal thoughts or intent to harm self/others
  • Severe abdominal pain with vomiting
  • High fever (≥39°C) with confusion or stiff neck

RED_FLAG (needs prompt medical attention):
  • Unexplained weight loss (>10 lbs in month)
  • Night sweats or fever for >1 week
  • Blood in urine, stool, or when coughing
  • Pain radiating to left arm, jaw, or between shoulder blades
  • Syncope (fainting) or near-fainting episodes
  • New lumps or masses anywhere on body
  • Rapidly worsening neurological symptoms
  • Severe pain (≥8/10 on pain scale)
  • Pregnancy possibility in females of childbearing age
  • Drug interaction risks with current medications
"""

_CONSULT_Q_PROMPT = """\
CONSULTATION HISTORY ({turn} exchanges completed):
{history}

PATIENT'S LATEST ANSWER:
"{answer}"

{urgency_note}

AREAS ALREADY COVERED: {covered_str}
CHIEF COMPLAINT FROM TRIAGE: {known_complaint}

NEXT AREA TO COVER:
{next_area}

Generate the NEXT clinical question. Ask about ONE topic only — the area listed above.
Do NOT combine multiple topics. Do NOT ask two things in one question.
Do NOT repeat a question already asked in CONSULTATION HISTORY above — check it carefully.
Follow up naturally based on what the patient just said before moving to the next area.
Build on their previous answer when possible to show you're listening.

Output ONLY the question text in {language} — no JSON, no labels, no prefix."""

_CONSULT_META_PROMPT = """\
CONSULTATION HISTORY ({turn} exchanges completed):
{history}

PATIENT'S LATEST ANSWER:
"{answer}"

{urgency_note}

Assess three things:
1. is_complete — Set TRUE when ALL of the following are sufficiently covered:
   ✓ Chief complaint identified and elaborated
   ✓ Timeline, severity, and symptom character well described  
   ✓ Modifying factors and associated symptoms explored
   ✓ Past medical history and current medications/allergies documented
   Set TRUE only if no critical clinical gaps remain that the physician genuinely cannot work without.
   Minimum {min_turns} questions must be asked unless all areas are thoroughly covered.

2. new_flags — Any NEW clinical red flags raised by the latest answer only?
   Check for: chest pain, breathing problems, severe headache, stroke signs, blood in urine/stool/vomit,
   fainting, severe pain (≥8/10), allergic reactions, suicidal thoughts, high fever with confusion.
   Use flag_type (CRITICAL_RED_FLAG or RED_FLAG) and description fields.

3. covered_areas — Which of these topic keys are now sufficiently answered, considering the
   FULL conversation so far? Choose only from: {area_keys}
   Return every key that is adequately covered, not just ones from this turn.

Return JSON only — no other text."""

_AREA_KEYS = [
    "chief_complaint",
    "timeline", 
    "severity",
    "character_location",
    "modifying_factors",
    "associated_symptoms",
    "past_history",
    "medications_allergies",
]

_AREA_PROMPTS = {
    "chief_complaint":     "Chief complaint — what is the main symptom or reason for the visit?",
    "timeline":            "Timeline — when did it start and how long has it been going on?", 
    "severity":            "Severity — how bad is it on a scale of 1-10 (10 = unbearable)?",
    "character_location":  "Character and location — what does it feel like and where exactly?",
    "modifying_factors":   "Modifying factors — what makes it better or worse?",
    "associated_symptoms": "Associated symptoms — anything else noticed alongside the main complaint?",
    "past_history":        "Past medical and surgical history — prior conditions, operations, hospitalizations",
    "medications_allergies": "Current medications and known allergies — what they take and any drug reactions",
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
            f"NOTE: {turn} exchanges completed. This is the LAST question allowed — "
            "the screening ends automatically after the patient answers. "
            "Ask about the single most important remaining gap, and set is_complete = true."
        )
    if turn >= MIN_CONSULTATION_TURNS:
        return (
            f"NOTE: {turn} exchanges completed. Check whether all required areas are covered. "
            "If they are sufficiently addressed, mark is_complete = true. Only continue if a key gap remains."
        )
    return ""


def _next_area(covered: list[str]) -> str:
    """Returns the FIRST uncovered area so the LLM asks one question at a time."""
    missing = [desc for key, desc in _AREA_PROMPTS.items() if key not in covered]
    if not missing:
        return "All essential areas appear covered."
    return missing[0]


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
        
        if known_complaint:
            prompt = (
                f"The triage is complete. The patient mentioned: '{known_complaint}' as their main concern. "
                f"Start the clinical history by greeting them by name and briefly acknowledging their "
                f"stated reason, then ask them to tell you more about it — specifically about: {next_area}. "
                f"Do NOT ask 'what brings you in' again — you already know. "
                f"Be warm and concise — one or two sentences in {self._lang_name}."
            )
        else:
            prompt = (
                f"The triage is complete. Start the clinical history by asking about: {next_area}. "
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
            urgency_note=_urgency_note(turn_count),
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
