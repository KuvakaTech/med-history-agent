from __future__ import annotations

from app.agent import llm
from app.clinical.context import ConsultationContext, DiagnosisResult

DIAGNOSIS_PROMPT = """You are a clinical decision support AI assisting a licensed physician.

Specialty: {specialty}
Clinical Flags:
{flags}

Patient Summary:
{summary}

Provide:
1. Differential diagnoses ranked from most to least likely, each with brief reasoning and ICD-10 code
2. Urgent concerns or red flags requiring immediate attention
3. Suggested diagnostic workup

This output is for physician review only — present as clinical suggestions, not definitive diagnoses."""


class DiagnosisService:
    async def diagnose(self, context: ConsultationContext) -> DiagnosisResult:
        summary_text = (
            str(context.summary) if context.summary
            else context.translated_transcript or context.raw_transcript
        )
        flags_text = (
            "\n".join(f"- [{f.flag_type}] {f.description}" for f in context.flags)
            or "None"
        )
        prompt = DIAGNOSIS_PROMPT.format(
            specialty=context.specialty.value.replace("_", " ").title(),
            flags=flags_text,
            summary=summary_text,
        )
        result = await llm.complete_structured(prompt, DiagnosisResult, max_tokens=2048)
        return result  # type: ignore[return-value]
