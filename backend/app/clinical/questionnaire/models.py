from pydantic import BaseModel


class ClinicalFlagPayload(BaseModel):
    flag_type: str
    description: str


class NextTurn(BaseModel):
    question_text: str
    is_complete: bool
    new_flags: list[ClinicalFlagPayload] = []
