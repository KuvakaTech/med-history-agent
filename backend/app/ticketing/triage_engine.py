"""Triage engine -- Phase 1 of the ticketing flow.

Max 10 turns. Collects name (with read-back), age, address, guardian, then
reason-for-visit to infer department. Uses the same "LLM judges its own
coverage each turn" pattern as LLMHistoryEngine.
"""
from __future__ import annotations

import asyncio
import logging
from typing import AsyncGenerator, Literal, Optional, Union

from pydantic import BaseModel

from app.agent import llm
from app.ticketing.models import TicketFlag, TicketQAEntry, TicketSession

log = logging.getLogger(__name__)

MAX_TRIAGE_TURNS = 10


# --------------------------------------------------------------------------- #
# LLM output schema
# --------------------------------------------------------------------------- #

class TriageMeta(BaseModel):
    is_complete: bool = False
    patient_name: Optional[str] = None
    patient_age: Optional[int] = None
    patient_address: Optional[str] = None
    guardian_name: Optional[str] = None
    category_guess: Optional[str] = None
    category_label: Optional[str] = None
    category_confidence: Literal["high", "low", "none"] = "none"
    new_flags: list[dict] = []


# --------------------------------------------------------------------------- #
# Prompts
# --------------------------------------------------------------------------- #

_TRIAGE_SYSTEM = """\
You are a warm, friendly female AI receptionist at a hospital conducting a brief pre-visit intake. Speak as a woman. In Hindi use feminine verb forms.

Your goal is to naturally learn -- in at most {max_turns} short exchanges, ONE question at a time:
  1. The patient's name — ask, then state it back as a short check (e.g. "Aapka naam Priya hai, theek hai?"). NEVER ask permission to repeat ("kya main ise dohra sakti hoon" is forbidden). If you did not hear it clearly, ask once more.
  2. The patient's age
  3. The patient's address
  4. Who came with them — ask "Kya aapke saath koi aaya hai?" Never say guardian/अभिभावक out loud. If they only give a relation (bhaiya, didi, mummy, papa, etc.), ask that person's name. If they came alone, skip.
  5. Why they came in today (to infer the correct department)

ANTI-LOOP — CRITICAL:
- If an answer is unclear, silent, or off-topic, ask that SAME question ONE more time.
- A third ask is the hard cap. Then leave that field blank, NEVER invent a value, and MOVE ON.
- Never freeze, never loop, never fail the session because a field is missing.

AVAILABLE DEPARTMENTS for this hospital:
{category_list}

RULES:
- Ask ONE question per turn. Short, warm, conversational -- like a receptionist, not a form.
- NEVER ask "which department do you need?" -- infer the department from symptoms/reason.
- NEVER re-ask something already clearly given AND confirmed.
- After greeting, ask name. When you have a name, state it back then wait. Then age, then address, then who came with them, then why they came.
- Do not invent names, ages, addresses, or companion names.
- At {max_turns} turns, set is_complete = true no matter what.
- category_guess MUST be one of the key values from the department list above, or null.
- category_confidence: "high" = clearly evident, "low" = possible, "none" = no clue yet.
- Always respond in the patient's language: {language}.
- Be empathetic and brief. This is intake, not an interrogation.
"""

_TRIAGE_OPENING = """\
The patient has just arrived at the hospital reception.
Gender: {gender}. Preferred language: {language}.

Greet them warmly in one sentence, then politely ask for their name.
Keep it friendly and welcoming - this is the first interaction.
Output ONLY the greeting + question text. No JSON. No labels."""

_TRIAGE_QUESTION_PROMPT = """\
Pre-visit intake -- turn {turn} of max {max_turns}.

Conversation so far:
{history}

Patient just said: "{latest_answer}"

What we already know (DO NOT ask about these again unless confirming a name you just heard):
  Name     : {known_name}
  Age      : {known_age}
  Address  : {known_address}
  Guardian : {known_guardian}
  Dept     : {known_category} (confidence: {known_confidence})

Order (one question at a time):
1. Name — if unclear, ask once more. If you just heard a name and have not confirmed it, state it back ("Aapka naam … hai, theek hai?"). Never ask if you may repeat it.
2. Age
3. Address
4. Companion — "Kya aapke saath koi aaya hai?" If they only give a relation, ask the person's name. Never say guardian.
5. Reason for visit (to infer department)

ANTI-LOOP: if this field was already asked twice without a clear answer, skip it (leave blank) and go to the next.
If name (or skipped) + age (or skipped) + address (or skipped) + companion (or skipped) + a reason are all done --> output exactly: [COMPLETE]
At turn {max_turns} always complete.

Respond in {language}. Output ONLY the question text (or [COMPLETE]). No JSON. No labels."""

_TRIAGE_META_PROMPT = """\
Pre-visit intake -- turn {turn} of max {max_turns}.

Conversation so far:
{history}

Patient just said: "{latest_answer}"

Extract from EVERYTHING said so far. Use ONLY what was clearly said. Never invent.
  patient_name        : string if clearly shared, null if declined/unclear/not provided
  patient_age         : integer if mentioned, else null
  patient_address     : string if clearly shared, else null
  guardian_name       : accompanying person's actual name if clearly shared, else null (relation-only words are not a name)
  category_guess      : one of the allowed keys below that best fits their reason, or null
  category_label      : matching human-readable label, or null
  category_confidence : "high" if clearly evident, "low" if uncertain, "none" if no clue
  is_complete         : true when identity fields have been asked-or-skipped AND a reason is known,
                        OR when turn count >= {max_turns}
  new_flags           : list of urgent clinical flags (CRITICAL_RED_FLAG, RED_FLAG, etc.)

Allowed category keys: {category_keys}

Return JSON only -- no explanation, no markdown."""

_TRIAGE_FORCED_META = """\
This is the FINAL triage turn ({max_turns}/{max_turns}).
Extract whatever has been clearly shared. Never invent missing fields. Set is_complete = true unconditionally.

Full conversation:
{history}
Patient final response: "{latest_answer}"

Allowed category keys: {category_keys}

Return JSON with is_complete = true. Include patient_address and guardian_name when clearly said, else null. No explanation."""


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
        known_address: Optional[str] = None,
        known_guardian: Optional[str] = None,
        known_category: Optional[str] = None,
        known_confidence: str = "none",
    ) -> AsyncGenerator[Union[str, dict], None]:
        """Yields str tokens then a final __done__ dict with TriageMeta fields."""
        turn_count = len(session.qa_log)
        history = _build_history(session.qa_log)
        is_last = turn_count >= MAX_TRIAGE_TURNS

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
                "patient_address": meta.patient_address,
                "guardian_name": meta.guardian_name,
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
            known_address=known_address or "unknown",
            known_guardian=known_guardian or "unknown",
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
            "patient_address": meta.patient_address,
            "guardian_name": meta.guardian_name,
            "category_guess": meta.category_guess,
            "category_label": meta.category_label,
            "category_confidence": meta.category_confidence,
            "new_flags": meta.new_flags or [],
        }
