from __future__ import annotations

from pydantic import BaseModel

from app.agent import llm
from app.clinical.context import ConsultationContext

COMPLETENESS_PROMPT = """You are a clinical audit assistant reviewing a patient history for completeness.

Required fields that must be present:
{required_fields}

Q&A collected so far:
{transcript}

Assess what is missing or insufficiently covered. Be specific.
Return JSON:
{{
  "missing_required": ["<field>", ...],
  "missing_recommended": ["<field>", ...],
  "ready_to_proceed": <true|false>
}}
Set ready_to_proceed = true if all required fields are covered at a minimum."""


class _Report(BaseModel):
    missing_required: list[str] = []
    missing_recommended: list[str] = []
    ready_to_proceed: bool = True


class CompletenessService:
    async def check(
        self, context: ConsultationContext, required_fields: str
    ) -> _Report:
        transcript = "\n".join(
            f"Q: {e.question_text}\nA: {e.answer}" for e in context.qa_log
        )
        prompt = COMPLETENESS_PROMPT.format(
            required_fields=required_fields,
            transcript=transcript or "(none)",
        )
        result = await llm.complete_structured(prompt, _Report)
        return result  # type: ignore[return-value]
