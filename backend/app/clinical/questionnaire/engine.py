"""Async LLM-driven clinical history-taking engine."""
from __future__ import annotations

import asyncio
import logging
from typing import AsyncGenerator, Union

from pydantic import BaseModel

from app.agent import llm
from app.clinical.context import ClinicalFlag, ConsultationContext, Specialty
from app.clinical.questionnaire.models import ClinicalFlagPayload, NextTurn

log = logging.getLogger(__name__)

# ─────────────────────────────────────────────
# Prompts
# ─────────────────────────────────────────────

SYSTEM_PROMPT = """You are a junior clinical screener — a medical AI assistant performing pre-consultation history taking BEFORE the patient meets the physician.

SPECIALTY: {specialty}

──────────────────────────────────────
ROLE
──────────────────────────────────────
You are NOT replacing the doctor. Your job: gather complete essential baseline history so the physician can make the most of their consultation time.

GOAL: Cover ALL six required areas as efficiently as possible — ideally in 5–7 questions — by combining related topics. The screening ends when you decide is_complete = true, not after a fixed number of questions.

──────────────────────────────────────
6 REQUIRED AREAS — all must be covered before you mark is_complete = true
──────────────────────────────────────
1. Chief complaint — what brings them in today (opening question only — ask this alone)
2. Timeline + character — onset, duration, severity (1–10 scale), location, quality
3. Modifying factors + associated symptoms — what makes it better or worse; what comes with it
4. Relevant past medical/surgical history — prior conditions, operations, hospitalisations
5. Current medications + known allergies
6. Key social or family context — ONLY if directly relevant to the chief complaint

──────────────────────────────────────
COMBINING STRATEGY
──────────────────────────────────────
• Q1 (opening): chief complaint only — warm, open-ended.
• Q2: combine areas 2 + 3 → e.g. "How long have you had this, how severe is it on a 1–10 scale, and does anything make it better or worse?"
• Q3: combine areas 4 + 5 → e.g. "Do you have any relevant past medical history or previous surgeries, and are you currently taking any medications or have known allergies?"
• Q4+: follow up on red flags, missing gaps, or area 6 if relevant. Continue until all areas are covered.
• Mark is_complete = true as soon as all required areas are sufficiently covered — do not keep asking once you have what the physician needs.

──────────────────────────────────────
BEHAVIOUR RULES
──────────────────────────────────────
• Warm, calm, professional tone. Plain accessible language.
• ALWAYS combine closely-related topics — never waste a question on a single narrow item.
• Do NOT ask about domains clearly irrelevant to the chief complaint.
• Never diagnose. Never suggest treatments or tests.
• The physician will conduct the detailed examination — you open the door.

──────────────────────────────────────
RED FLAG DETECTION — check EVERY answer
──────────────────────────────────────
CRITICAL_RED_FLAG:
  • Chest pain/tightness (possible ACS)
  • Acute severe breathlessness
  • Sudden severe headache ("worst headache of my life")
  • Stroke symptoms: facial droop, arm weakness, slurred speech
  • Haematemesis or melaena
  • Loss of consciousness
  • Anaphylaxis history
  • Active suicidal ideation or intent to harm
  • Cauda equina symptoms

RED_FLAG:
  • Unexplained weight loss · Night sweats
  • Blood in urine, stool, or sputum
  • Pain radiating to left arm or jaw
  • High fever (≥ 39 °C) with rigors · Syncope or near-syncope
  • Painless lump or mass · Rapidly worsening neurological symptoms
  • Relevant drug interaction risk
  • Pregnancy possibility in females of childbearing age
  • High pain severity (≥ 8/10)
  • Significant family history of early cardiac disease or cancer
"""

OPENING_PROMPT_COLD = (
    "No history has been collected yet. Open the pre-consultation screening: "
    "introduce yourself in ONE brief sentence as a clinical assistant, "
    "then ask the patient's main concern in a warm, open-ended way. "
    "Be concise and welcoming."
)

OPENING_PROMPT_WITH_NAME = (
    "Patient details already collected at intake:\n"
    "{patient_context}\n\n"
    "Open the pre-consultation screening: greet the patient by name and introduce yourself "
    "in ONE brief sentence as a clinical assistant, then ask what brings them in today "
    "in a warm, open-ended way. Be concise and welcoming."
)

OPENING_PROMPT_WITH_COMPLAINT = (
    "Patient details already collected at intake:\n"
    "{patient_context}\n\n"
    "Open the pre-consultation screening: greet the patient by name, "
    "briefly acknowledge their stated reason for the visit, "
    "then ask them to tell you more about it — when it started, how severe it is (1–10), "
    "and what it feels like. Do NOT ask 'what brings you in' — you already know. "
    "Be warm and concise — one or two sentences."
)

# ── Streaming path: two focused prompts run concurrently ──

QUESTION_STREAM_PROMPT = """CONSULTATION HISTORY ({turn_count} exchanges completed):
{history}

PATIENT'S LATEST ANSWER:
{latest_answer}

{urgency_note}

AREAS STILL TO COVER:
{uncovered_areas}

Generate the NEXT clinical question. Combine as many uncovered areas as naturally possible into ONE question — do not ask one item per question.
Output ONLY the question text — no JSON, no labels, no prefix."""

META_PROMPT = """CONSULTATION HISTORY ({turn_count} exchanges completed):
{history}

PATIENT'S LATEST ANSWER:
{latest_answer}

{urgency_note}

Assess two things:
1. is_complete — Set TRUE when ALL of the following are sufficiently covered:
   ✓ Chief complaint identified
   ✓ Duration, severity, and symptom character
   ✓ Modifying factors or associated symptoms
   ✓ Past medical history and medications/allergies
   Set TRUE even if some details are imperfect — the physician will probe further in consultation.
   Set FALSE only if a critical clinical gap remains that the physician genuinely cannot work without.
2. new_flags — Any NEW clinical red flags raised by the latest answer?

Return JSON only — no other text."""

# Fallback for non-streaming path
TURN_PROMPT = """CONSULTATION HISTORY ({turn_count} exchanges completed):
{history}

PATIENT'S LATEST ANSWER:
{latest_answer}

{urgency_note}

AREAS STILL TO COVER:
{uncovered_areas}

Generate the next follow-up question combining any uncovered areas, or mark is_complete = true if all required areas are covered.
Evaluate the latest answer for red flags and include in new_flags."""


# ─────────────────────────────────────────────
# Schemas
# ─────────────────────────────────────────────

class NextTurnMeta(BaseModel):
    is_complete: bool
    new_flags: list[ClinicalFlagPayload] = []


# ─────────────────────────────────────────────
# Engine
# ─────────────────────────────────────────────

class LLMHistoryEngine:
    def __init__(
        self,
        specialty: Specialty,
        language: str | None = None,
        patient_name: str | None = None,
        patient_age: int | None = None,
        patient_gender: str | None = None,
        chief_complaint: str | None = None,
    ) -> None:
        self.specialty = specialty
        self._system = SYSTEM_PROMPT.format(
            specialty=specialty.value.replace("_", " ").title(),
        ) + _patient_context_block(patient_name, patient_age, patient_gender, chief_complaint) + _language_instruction(language)

    async def opening_question(
        self,
        patient_name: str | None = None,
        patient_age: int | None = None,
        patient_gender: str | None = None,
        chief_complaint: str | None = None,
    ) -> str:
        parts = []
        if patient_name:
            parts.append(f"Name: {patient_name}")
        if patient_age:
            parts.append(f"Age: {patient_age}")
        if patient_gender:
            parts.append(f"Gender: {patient_gender}")

        if chief_complaint:
            parts.append(f"Chief complaint: {chief_complaint}")
            prompt = OPENING_PROMPT_WITH_COMPLAINT.format(
                patient_context="\n".join(parts)
            )
        elif parts:
            prompt = OPENING_PROMPT_WITH_NAME.format(
                patient_context="\n".join(parts)
            )
        else:
            prompt = OPENING_PROMPT_COLD

        turn = await llm.complete_structured(
            prompt=prompt,
            schema=NextTurn,
            system=self._system,
            fast=True,
        )
        return turn.question_text  # type: ignore[union-attr]

    async def next_turn(
        self, context: ConsultationContext, latest_answer: str
    ) -> tuple[ConsultationContext, NextTurn]:
        """Non-streaming turn."""
        history = self._build_history(context)
        turn_count = len(context.qa_log)
        prompt = TURN_PROMPT.format(
            history=history or "(no prior exchanges)",
            latest_answer=latest_answer,
            turn_count=turn_count,
            urgency_note=_urgency_note(turn_count),
            uncovered_areas=_uncovered_areas(history),
        )
        turn: NextTurn = await llm.complete_structured(  # type: ignore[assignment]
            prompt=prompt,
            schema=NextTurn,
            system=self._system,
            fast=True,
        )

        new_flags: list[ClinicalFlag] = []
        for fp in turn.new_flags:
            flag = ClinicalFlag(flag_type=fp.flag_type, description=fp.description)
            context.flags.append(flag)
            new_flags.append(flag)

        turn._resolved_flags = new_flags  # type: ignore[attr-defined]
        return context, turn

    async def next_turn_stream(
        self, context: ConsultationContext, latest_answer: str
    ) -> AsyncGenerator[Union[str, dict], None]:
        """
        Streaming turn. Yields str tokens then a final dict:
          {"__done__": True, "is_complete": bool, "question_text": str, "new_flags": [...]}

        Two concurrent calls:
          • stream_complete  → yields question tokens one by one
          • complete_structured (NextTurnMeta) → is_complete + flags
        """
        history = self._build_history(context)
        turn_count = len(context.qa_log)
        urgency_note = _urgency_note(turn_count)

        q_prompt = QUESTION_STREAM_PROMPT.format(
            history=history or "(no prior exchanges)",
            latest_answer=latest_answer,
            turn_count=turn_count,
            urgency_note=urgency_note,
            uncovered_areas=_uncovered_areas(history),
        )
        m_prompt = META_PROMPT.format(
            history=history or "(no prior exchanges)",
            latest_answer=latest_answer,
            turn_count=turn_count,
            urgency_note=urgency_note,
        )

        meta_task: asyncio.Task[NextTurnMeta] = asyncio.create_task(
            llm.complete_structured(m_prompt, NextTurnMeta, system=self._system, fast=True)
        )

        question_text = ""
        try:
            async for token in llm.stream_complete(q_prompt, system=self._system, fast=True):
                question_text += token
                yield token
        except Exception as exc:
            log.error("Question stream failed: %s", exc)
            meta_task.cancel()
            raise

        try:
            meta: NextTurnMeta = await meta_task
        except Exception as exc:
            log.error("Meta call failed: %s", exc)
            meta = NextTurnMeta(is_complete=False, new_flags=[])

        new_flags: list[ClinicalFlag] = []
        for fp in meta.new_flags:
            flag = ClinicalFlag(flag_type=fp.flag_type, description=fp.description)
            context.flags.append(flag)
            new_flags.append(flag)

        yield {
            "__done__": True,
            "is_complete": meta.is_complete,
            # Always return the streamed text so the handler can decide
            "question_text": question_text.strip(),
            "new_flags": new_flags,
        }

    def get_required_fields(self) -> str:
        return (
            "- Chief complaint\n"
            "- Onset, duration, and severity (1–10 scale)\n"
            "- Character, location, and modifying factors\n"
            "- Associated symptoms\n"
            "- Relevant past medical history and surgeries\n"
            "- Current medications and known allergies\n"
        )

    @staticmethod
    def _build_history(context: ConsultationContext) -> str:
        return "\n".join(
            f"Q: {e.question_text}\nA: {e.answer}" for e in context.qa_log
        )


def _urgency_note(turn_count: int) -> str:
    if turn_count >= 7:
        return (
            f"NOTE: {turn_count} exchanges completed. All essential areas should be covered by now. "
            "Set is_complete = true unless a genuinely critical clinical gap remains."
        )
    if turn_count >= 5:
        return (
            f"NOTE: {turn_count} exchanges completed. If all required areas are covered, "
            "mark is_complete = true now. Only continue if a key gap remains."
        )
    return ""


def _patient_context_block(
    name: str | None,
    age: int | None,
    gender: str | None,
    chief_complaint: str | None,
) -> str:
    parts = []
    if name:
        parts.append(f"Name: {name}")
    if age:
        parts.append(f"Age: {age}")
    if gender:
        parts.append(f"Gender: {gender}")
    if chief_complaint:
        parts.append(f"Chief complaint (pre-stated): {chief_complaint}")
    if not parts:
        return ""
    return (
        "\n\n──────────────────────────────────────\n"
        "PATIENT DEMOGRAPHICS (collected at intake)\n"
        "──────────────────────────────────────\n"
        + "\n".join(parts)
        + "\nUse the patient's name when appropriate. "
        "Chief complaint is already known — do NOT ask 'what brings you in'. "
        "Focus history taking on elaborating and exploring the stated complaint."
    )


def _language_instruction(language: str | None) -> str:
    if not language:
        return ""
    lang = language.strip()
    if lang.lower() in ("en", "english"):
        return ""
    return (
        f"\n\n──────────────────────────────────────\n"
        f"LANGUAGE\n"
        f"──────────────────────────────────────\n"
        f"The patient has selected {lang} as their language. "
        f"Ask ALL your questions in {lang}. "
        f"Do not switch to English at any point during history taking."
    )


def _uncovered_areas(history: str) -> str:
    """Keyword heuristic — tells the question generator what's still missing."""
    h = history.lower()
    missing: list[str] = []

    if not any(k in h for k in [
        "how long", "since when", "started", "duration", "days ago", "weeks ago",
        "months ago", "onset", "sever", "scale", "out of 10", "1 to 10", "rate",
        "pain level", "constant", "comes and goes",
    ]):
        missing.append("- Duration, onset, severity (1–10 scale), character, location")

    if not any(k in h for k in [
        "better", "worse", "aggravat", "reliev", "associat", "accompan",
        "other symptom", "also experienc", "spread", "radiat", "trigger",
    ]):
        missing.append("- Modifying factors (better/worse) and associated symptoms")

    if not any(k in h for k in [
        "past", "history", "previous", "before", "condition", "surgery",
        "operation", "diagnos", "chronic", "medical histor", "hospitaliz", "hospital",
    ]):
        missing.append("- Past medical history and previous surgeries")

    if not any(k in h for k in [
        "medication", "medicine", "drug", "tablet", "pill", "allerg",
        "taking", "prescribed", "supplement", "inject", "inhaler", "no medication",
    ]):
        missing.append("- Current medications and known allergies")

    return "\n".join(missing) if missing else "All essential areas appear covered."
