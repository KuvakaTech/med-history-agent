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

# Screening length. turn_count == len(qa_log) == number of questions already asked and
# answered, so it equals the total question count once the screening ends. MIN forces
# continuation (unless nothing relevant remains to ask) so screenings aren't too short;
# MAX is a hard stop so the patient is never asked an 11th question.
MIN_TURNS = 7
MAX_TURNS = 10

# Canonical topic keys the LLM classifies coverage against each turn — language-agnostic,
# since the LLM (not a keyword match) judges whether the topic was addressed.
AREA_DESCRIPTIONS: dict[str, str] = {
    "timeline": "- Timeline: when did it start and how long has it been going on?",
    "severity": "- Severity: how bad is it on a scale of 1–10?",
    "character_location": "- Character and location: what does it feel like and where exactly?",
    "modifying_factors": "- Modifying factors: what makes it better or worse?",
    "associated_symptoms": "- Associated symptoms: anything else noticed alongside it?",
    "past_history": "- Past medical and surgical history: any prior conditions or operations?",
    "medications": "- Current medications: what medications are they currently taking?",
    "allergies": "- Known allergies: any known drug or other allergies?",
}
_ALL_COVERED = "All essential areas appear covered."
_AREA_KEYS = ", ".join(AREA_DESCRIPTIONS.keys())

# ─────────────────────────────────────────────
# Prompts
# ─────────────────────────────────────────────

SYSTEM_PROMPT = """You are a junior clinical screener — a medical AI assistant performing pre-consultation history taking BEFORE the patient meets the physician.

SPECIALTY: {specialty}

──────────────────────────────────────
ROLE
──────────────────────────────────────
You are NOT replacing the doctor. Your job: gather complete essential baseline history so the physician can make the most of their consultation time.

GOAL: Cover ALL six required areas by asking ONE focused question at a time. Each question should address a single topic only. The screening takes 7–10 questions and must NEVER exceed 10. The screening ends when you decide is_complete = true.

• NEVER repeat a question you have already asked — check the CONSULTATION HISTORY below before every question. This applies even if the patient answered in a different language or you would phrase it differently; if the underlying topic was already asked, move to a different, uncovered topic instead.

──────────────────────────────────────
6 REQUIRED AREAS — all must be covered before you mark is_complete = true
──────────────────────────────────────
1. Chief complaint — what brings them in today
2. Timeline — when it started, how long it has been going on
3. Severity — how bad it is (1–10 scale)
4. Character + location — what it feels like, where exactly
5. Modifying factors — what makes it better or worse
6. Associated symptoms — anything else they have noticed alongside it
7. Relevant past medical/surgical history — prior conditions, operations, hospitalisations
8. Current medications — what they are currently taking
9. Known allergies
10. Key social or family context — ONLY if directly relevant to the chief complaint

──────────────────────────────────────
QUESTIONING RULES — CRITICAL
──────────────────────────────────────
• Ask ONE question per turn. ONE topic only. Never bundle multiple questions into one.
• WRONG: "How long have you had this, how severe is it on a 1–10 scale, and does anything make it better or worse?"
• RIGHT: "How long have you been experiencing this?"  → wait for answer → "On a scale of 1–10, how would you rate the severity?" → wait → "Is there anything that makes it better or worse?"
• Each question must be short, clear, and focused on a single piece of information.
• Do NOT ask about domains clearly irrelevant to the chief complaint.
• Never diagnose. Never suggest treatments or tests.
• The physician will conduct the detailed examination — you open the door.

──────────────────────────────────────
BEHAVIOUR RULES
──────────────────────────────────────
• Warm, calm, professional tone. Plain accessible language.
• One question. One topic. Every single time.
• Follow up naturally based on what the patient just said before moving to the next area.
• Mark is_complete = true only after all required areas are sufficiently covered.

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

NEXT AREA TO COVER:
{uncovered_areas}

Generate the NEXT clinical question. Ask about ONE topic only — the first item listed above.
Do NOT combine multiple topics. Do NOT ask two things in one question.
Do NOT repeat a question already asked in CONSULTATION HISTORY above — check it carefully,
even if the patient's answers are in a different language than this instruction.
Output ONLY the question text — no JSON, no labels, no prefix."""

META_PROMPT = """CONSULTATION HISTORY ({turn_count} exchanges completed):
{history}

PATIENT'S LATEST ANSWER:
{latest_answer}

{urgency_note}

Assess three things:
1. is_complete — Set TRUE when ALL of the following are sufficiently covered:
   ✓ Chief complaint identified
   ✓ Duration, severity, and symptom character
   ✓ Modifying factors or associated symptoms
   ✓ Past medical history and medications/allergies
   Set TRUE even if some details are imperfect — the physician will probe further in consultation.
   Set FALSE only if a critical clinical gap remains that the physician genuinely cannot work without.
2. new_flags — Any NEW clinical red flags raised by the latest answer?
3. covered_areas — Which of these topic keys are now sufficiently answered, considering the
   FULL conversation so far (in whatever language the patient used)? Choose only from exactly
   these keys: {area_keys}. Return every key that applies, not just ones from this turn.

Return JSON only — no other text."""

# Fallback for non-streaming path
TURN_PROMPT = """CONSULTATION HISTORY ({turn_count} exchanges completed):
{history}

PATIENT'S LATEST ANSWER:
{latest_answer}

{urgency_note}

NEXT AREA TO COVER:
{uncovered_areas}

Generate the next follow-up question. Ask about ONE topic only — the first item listed above.
Do NOT combine multiple topics into a single question.
Do NOT repeat a question already asked in CONSULTATION HISTORY above — check it carefully,
even if the patient's answers are in a different language than this instruction.
Mark is_complete = true only if all required areas are covered.
Evaluate the latest answer for red flags and include in new_flags.
covered_areas — Which of these topic keys are now sufficiently answered, considering the FULL
conversation so far? Choose only from exactly these keys: {area_keys}. Return every key that
applies, not just ones from this turn."""


# ─────────────────────────────────────────────
# Schemas
# ─────────────────────────────────────────────

class NextTurnMeta(BaseModel):
    is_complete: bool
    new_flags: list[ClinicalFlagPayload] = []
    covered_areas: list[str] = []


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

        if turn_count >= MAX_TURNS:
            turn = NextTurn(question_text="", is_complete=True, new_flags=[])
            turn._resolved_flags = []  # type: ignore[attr-defined]
            return context, turn

        uncovered = _uncovered_areas(context.covered_areas)
        prompt = TURN_PROMPT.format(
            history=history or "(no prior exchanges)",
            latest_answer=latest_answer,
            turn_count=turn_count,
            urgency_note=_urgency_note(turn_count),
            uncovered_areas=uncovered,
            area_keys=_AREA_KEYS,
        )
        turn: NextTurn = await llm.complete_structured(  # type: ignore[assignment]
            prompt=prompt,
            schema=NextTurn,
            system=self._system,
            fast=True,
        )

        context.covered_areas = sorted(
            set(context.covered_areas) | {a for a in turn.covered_areas if a in AREA_DESCRIPTIONS}
        )

        if turn_count < MIN_TURNS and uncovered != _ALL_COVERED and turn.question_text:
            turn.is_complete = False

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

        if turn_count >= MAX_TURNS:
            yield {"__done__": True, "is_complete": True, "question_text": "", "new_flags": []}
            return

        urgency_note = _urgency_note(turn_count)
        uncovered = _uncovered_areas(context.covered_areas)

        q_prompt = QUESTION_STREAM_PROMPT.format(
            history=history or "(no prior exchanges)",
            latest_answer=latest_answer,
            turn_count=turn_count,
            urgency_note=urgency_note,
            uncovered_areas=uncovered,
        )
        m_prompt = META_PROMPT.format(
            history=history or "(no prior exchanges)",
            latest_answer=latest_answer,
            turn_count=turn_count,
            urgency_note=urgency_note,
            area_keys=_AREA_KEYS,
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

        context.covered_areas = sorted(
            set(context.covered_areas) | {a for a in meta.covered_areas if a in AREA_DESCRIPTIONS}
        )

        stripped_question = question_text.strip()
        if turn_count < MIN_TURNS and uncovered != _ALL_COVERED and stripped_question:
            meta.is_complete = False

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
    if turn_count >= MAX_TURNS - 1:
        return (
            f"NOTE: {turn_count} exchanges completed. This is the LAST question allowed — "
            "the screening ends automatically right after the patient answers it. "
            "Ask about the single most important remaining gap, and set is_complete = true."
        )
    if turn_count >= MIN_TURNS:
        return (
            f"NOTE: {turn_count} exchanges completed. Check whether all required areas are covered. "
            "If they are, mark is_complete = true. Only continue if a key gap remains."
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


def _uncovered_areas(covered: list[str]) -> str:
    """Returns the FIRST uncovered area so the LLM asks one question at a time.

    `covered` is judged by the LLM itself each turn (see NextTurnMeta.covered_areas /
    NextTurn.covered_areas) rather than by keyword-matching the transcript — a keyword
    heuristic only recognises English words and silently breaks for any other patient
    language, repeatedly flagging areas as "uncovered" that were already answered.
    """
    missing = [desc for key, desc in AREA_DESCRIPTIONS.items() if key not in covered]
    if not missing:
        return _ALL_COVERED
    return missing[0]
