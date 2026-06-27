from __future__ import annotations

from app.agent import llm
from app.clinical.context import ConsultationContext, PrescriptionResult

PRESCRIPTION_PROMPT = """You are a clinical pharmacology AI assisting a licensed physician.

Specialty: {specialty}
Confirmed Diagnosis: {diagnosis}

Patient Context (summary):
{summary}

Current Medications: {medications}
Allergies: {allergies}

Generate a treatment plan including:
1. Pharmacological interventions (drug, dose, frequency, duration, warnings)
2. Non-pharmacological recommendations
3. Follow-up schedule
4. Referrals if needed
5. Contraindication warnings

⚠️ This plan requires physician review and approval before dispensing.
Return as JSON matching the PrescriptionResult schema."""


class PrescriptionService:
    async def prescribe(
        self, context: ConsultationContext, confirmed_diagnosis: str
    ) -> PrescriptionResult:
        summary_text = str(context.summary) if context.summary else context.raw_transcript

        meds = ""
        allergies = ""
        for entry in context.qa_log:
            q_lower = entry.question_text.lower()
            if "medication" in q_lower or "drug" in q_lower:
                meds = entry.answer
            if "allerg" in q_lower:
                allergies = entry.answer

        prompt = PRESCRIPTION_PROMPT.format(
            specialty=context.specialty.value.replace("_", " ").title(),
            diagnosis=confirmed_diagnosis,
            summary=summary_text[:2000],
            medications=meds or "Not specified",
            allergies=allergies or "Not specified",
        )
        result = await llm.complete_structured(prompt, PrescriptionResult, max_tokens=2048)
        return result  # type: ignore[return-value]
