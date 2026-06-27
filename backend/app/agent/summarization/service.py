from __future__ import annotations

from app.agent import llm

SUMMARIZE_PROMPT = """Prepare a structured SOAP clinical note from the following patient Q&A transcript.

Use STRICTLY and EXCLUSIVELY the information in the transcript.
Do not add, assume, infer, or expand on details not explicitly stated.
Use professional clinical language.

Format the output as JSON with these sections:
{{
  "subjective": {{
    "chief_complaint": "",
    "history_of_presenting_illness": "",
    "past_medical_history": "",
    "surgical_history": "",
    "medications": "",
    "allergies": "",
    "family_history": "",
    "social_history": "",
    "review_of_systems": ""
  }},
  "objective": {{
    "vital_signs": "",
    "physical_examination": ""
  }},
  "assessment": "",
  "plan": ""
}}

Set fields to null if not covered in the transcript.

Transcript:
{transcript}"""


class SummarizationService:
    async def summarize(self, transcript: str) -> dict:
        from pydantic import BaseModel
        from typing import Optional

        class SubjectiveNote(BaseModel):
            chief_complaint: Optional[str] = None
            history_of_presenting_illness: Optional[str] = None
            past_medical_history: Optional[str] = None
            surgical_history: Optional[str] = None
            medications: Optional[str] = None
            allergies: Optional[str] = None
            family_history: Optional[str] = None
            social_history: Optional[str] = None
            review_of_systems: Optional[str] = None

        class ObjectiveNote(BaseModel):
            vital_signs: Optional[str] = None
            physical_examination: Optional[str] = None

        class SOAPNote(BaseModel):
            subjective: SubjectiveNote = SubjectiveNote()
            objective: ObjectiveNote = ObjectiveNote()
            assessment: Optional[str] = None
            plan: Optional[str] = None

        prompt = SUMMARIZE_PROMPT.format(transcript=transcript)
        result = await llm.complete_structured(prompt, SOAPNote, max_tokens=2048)
        return result.model_dump(mode="json")  # type: ignore[union-attr]
