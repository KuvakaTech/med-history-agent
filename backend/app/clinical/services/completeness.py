from __future__ import annotations

from app.agent import llm
from app.clinical.context import CompletenessReport, ConsultationContext

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


class CompletenessService:
    async def check(
        self, context: ConsultationContext, required_fields: str
    ) -> CompletenessReport:
        transcript = "\n".join(
            f"Q: {e.question_text}\nA: {e.answer}" for e in context.qa_log
        )
        prompt = COMPLETENESS_PROMPT.format(
            required_fields=required_fields,
            transcript=transcript or "(none)",
        )
        result = await llm.complete_structured(prompt, CompletenessReport)
        return result  # type: ignore[return-value]
