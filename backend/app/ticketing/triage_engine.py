"""Triage engine -- Phase 1 of the ticketing flow.

Max 3 turns. Extracts: patient name, age, and department category.
Uses the same "LLM judges its own coverage each turn" pattern as LLMHistoryEngine.

Key improvements over v1:
- Question prompt now shows what is already known so LLM never re-asks.
- Early-exit: if meta marks is_complete=true before max turns, we stop immediately.
- Opening question leads with reason-for-visit (not name/age) to infer category faster.
- Forced-meta turn now also generates a transitional sentence for smooth handoff.
"""
from __future__ import annotations

import asyncio
import logging
from typing import AsyncGenerator, Literal, Optional, Union

from pydantic import BaseModel

from app.agent import llm
from app.ticketing.models import TicketFlag, TicketQAEntry, TicketSession

log = logging.getLogger(__name__)

MAX_TRIAGE_TURNS = 3


# --------------------------------------------------------------------------- #
# LLM output schema
# --------------------------------------------------------------------------- #

class TriageTurn(BaseModel):
    question_text: str
    patient_name: Optional[str] = None
    patient_age: Optional[int] = None
    # Must match an active TicketCategory.key for this hospital (or null)
    category_guess: Optional[str] = None
    category_label: Optional[str] = None  # human-readable label
    category_confidence: Literal["high", "low", "none"] = "none"
    is_complete: bool = False
    new_flags: list[dict] = []


class TriageMeta(BaseModel):
    patient_name: Optional[str] = None
    patient_age: Optional[int] = None
    category_guess: Optional[str] = None
    category_label: Optional[str] = None
    category_confidence: Literal["high", "low", "none"] = "none"
    is_complete: bool = False
    new_flags: list[dict] = []


# --------------------------------------------------------------------------- #
# Prompts
# --------------------------------------------------------------------------- #

_TRIAGE_SYSTEM = """\
You are a warm, friendly AI receptionist at a hospital conducting a brief pre-visit intake.

Your goal is to naturally learn -- in at most {max_turns} short exchanges:
  1. The patient's reason for visiting (to infer the correct department)
  2. The patient's age
  3. The patient's name (optional -- never push if they do not share it)

AVAILABLE DEPARTMENTS for this hospital:
{category_list}

RULES:
- Ask ONE question per turn. Short, warm, conversational -- like a receptionist, not a form.
- NEVER ask "which department do you need?" -- infer the department from symptoms/reason.
- NEVER re-ask something the patient already told you in this conversation.
  If you already know their name, age, or department -- do NOT mention or ask about it again.
- Name is optional. If the patient has not volunteered it after your first question, skip it.
- As soon as you have (name or name-skipped) + age + high-confidence department, stop asking.
  Do not pad with extra questions just to reach {max_turns}.
- At {max_turns} turns, set is_complete = true no matter what.
- category_guess MUST be one of the key values from the department list above, or null.
- category_confidence: "high" = clearly evident, "low" = possible, "none" = no clue yet.
- Always respond in the patient's language: {language}.
- Be empathetic and brief. This is intake, not an interrogation.
"""

_TRIAGE_OPENING = """\
The patient has just arrived at the hospital reception.
Gender: {gender}. Preferred language: {language}.

Greet them warmly in one sentence, then ask a single open question about
what brings them in today. Lead with their reason for visiting -- do NOT
ask for their name or age first. That feels clinical; let them share why
they are here and gather name/age naturally after.

Output ONLY the greeting + question text. No JSON. No labels."""

_TRIAGE_QUESTION_PROMPT = """\
Pre-visit intake -- turn {turn} of max {max_turns}.

Conversation so far:
{history}

Patient just said: "{latest_answer}"

What we already know (DO NOT ask about these again):
  Name   : {known_name}
  Age    : {known_age}
  Dept   : {known_category} (confidence: {known_confidence})

Decision:
- If name (or skipped) + age + high-confidence dept are ALL known --> output exactly: [COMPLETE]
- Otherwise, ask the ONE most important missing piece in a natural, conversational way.
  Follow up on what the patient just said when possible -- do not jump to a new topic abruptly.

Respond in {language}. Output ONLY the question text (or [COMPLETE]). No JSON. No labels."""

_TRIAGE_META_PROMPT = """\
Pre-visit intake -- turn {turn} of max {max_turns}.

Conversation so far:
{history}

Patient just said: "{latest_answer}"

Extract from EVERYTHING said so far:
  patient_name        : string if clearly shared, else null
  patient_age         : integer if mentioned, else null
  category_guess      : one of the allowed keys below that best fits their reason, or null
  category_label      : matching human-readable label, or null
  category_confidence : "high" if clearly evident, "low" if uncertain, "none" if no clue
  is_complete         : true when (name known OR name not offered) AND age known
                        AND category_confidence == "high",
                        OR when turn count >= {max_turns}
  new_flags           : list of urgent clinical flags (CRITICAL_RED_FLAG, RED_FLAG, etc.)

Allowed category keys: {category_keys}

Return JSON only -- no explanation, no markdown."""

_TRIAGE_FORCED_META = """\
This is the FINAL triage turn ({max_turns}/{max_turns}).
Extract whatever has been shared and set is_complete = true unconditionally.

Full conversation:
{history}
Patient final response: "{latest_answer}"

Allowed category keys: {category_keys}

Return JSON with is_complete = true. No explanation."""


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #

def _build_history(qa_log: list[TicketQAEntry]) -> str:
    if not qa_log:
        return "(start of conversation)"
    return "\n".join(
        f"  Agent  : {e.question_text}\n  Patient: {e.answer}" for e in qa_log
    )


def _category_list_str(categories: list) -> str:
    return "\n".join(f'  - key: "{c.key}", department: "{c.label}"' for c in categories)


def _build_category_list(categories: list) -> str:
    return "\n".join(
        f'  key="{c.key}" -> {c.label}' for c in categories
    )


def _language_name(code: str) -> str:
    mapping = {
        "hi": "Hindi",
        "en": "English",
        "mr": "Marathi",
        "gu": "Gujarati",
        "ta": "Tamil",
        "te": "Telugu",
        "kn": "Kannada",
        "bn": "Bengali",
        "pa": "Punjabi",
    }
    return mapping.get(code.lower(), code)


# --------------------------------------------------------------------------- #
# Engine
# --------------------------------------------------------------------------- #

class TriageEngine:
    def __init__(
        self,
        categories: list,  # list[TicketCategory]
        language: str = "hi",
        gender: str = "unknown",
    ) -> None:
        self._categories = categories
        self._language = language
        self._gender = gender
        self._category_keys = ", ".join(f'"{c.key}"' for c in categories)
        self._system = _TRIAGE_SYSTEM.format(
            max_turns=MAX_TRIAGE_TURNS,
            category_list=_build_category_list(categories),
            language=_language_name(language),
        )

    async def opening_question(self) -> str:
        prompt = _TRIAGE_OPENING.format(
            gender=self._gender,
            language=_language_name(self._language),
        )
        return await llm.complete(prompt, system=self._system, fast=True)

    async def next_turn_stream(
        self,
        session: TicketSession,
        latest_answer: str,
        # Pass accumulated meta from previous turns so we never re-ask known facts
        known_name: Optional[str] = None,
        known_age: Optional[int] = None,
        known_category: Optional[str] = None,
        known_confidence: str = "none",
    ) -> AsyncGenerator[Union[str, dict], None]:
        """Yields str tokens then a final __done__ dict with TriageMeta fields."""
        turn_count = len(session.qa_log)
        history = _build_history(session.qa_log)
        is_last = turn_count >= MAX_TRIAGE_TURNS - 1

        if is_last:
            # Forced completion -- extract meta and end triage
            meta_result = await llm.complete_structured(
                _TRIAGE_FORCED_META.format(
                    max_turns=MAX_TRIAGE_TURNS,
                    history=history,
                    latest_answer=latest_answer,
                    category_keys=self._category_keys,
                ),
                TriageMeta,
                system=self._system,
                fast=True,
            )
            meta: TriageMeta = meta_result  # type: ignore[assignment]
            meta.is_complete = True
            yield {
                "__done__": True,
                "is_complete": True,
                "question_text": "",
                "patient_name": meta.patient_name,
                "patient_age": meta.patient_age,
                "category_guess": meta.category_guess,
                "category_label": meta.category_label,
                "category_confidence": meta.category_confidence,
                "new_flags": meta.new_flags or [],
            }
            return

        # Build prompts with known-context injected
        q_prompt = _TRIAGE_QUESTION_PROMPT.format(
            turn=turn_count + 1,
            max_turns=MAX_TRIAGE_TURNS,
            history=history,
            latest_answer=latest_answer,
            known_name=known_name or "unknown",
            known_age=str(known_age) if known_age is not None else "unknown",
            known_category=known_category or "unknown",
            known_confidence=known_confidence,
            language=_language_name(self._language),
        )
        m_prompt = _TRIAGE_META_PROMPT.format(
            turn=turn_count + 1,
            max_turns=MAX_TRIAGE_TURNS,
            history=history,
            latest_answer=latest_answer,
            category_keys=self._category_keys,
        )

        meta_task: asyncio.Task = asyncio.create_task(
            llm.complete_structured(m_prompt, TriageMeta, system=self._system, fast=True)
        )

        question_text = ""
        try:
            async for token in llm.stream_complete(q_prompt, system=self._system, fast=True):
                # If LLM decided everything is known, skip streaming
                if question_text == "" and token.strip().startswith("[COMPLETE]"):
                    break
                question_text += token
                yield token
        except Exception as exc:
            log.error("TriageEngine question stream failed: %s", exc)
            meta_task.cancel()
            raise

        # If LLM output [COMPLETE], treat as early exit
        if "[COMPLETE]" in question_text:
            question_text = ""

        try:
            meta = await meta_task  # type: ignore[assignment]
        except Exception as exc:
            log.warning("TriageEngine meta call failed: %s", exc)
            meta = TriageMeta()

        # If question was suppressed due to [COMPLETE], force is_complete
        if not question_text.strip():
            meta.is_complete = True

        yield {
            "__done__": True,
            "is_complete": meta.is_complete,
            "question_text": question_text.strip(),
            "patient_name": meta.patient_name,
            "patient_age": meta.patient_age,
            "category_guess": meta.category_guess,
            "category_label": meta.category_label,
            "category_confidence": meta.category_confidence,
            "new_flags": meta.new_flags or [],
        }
