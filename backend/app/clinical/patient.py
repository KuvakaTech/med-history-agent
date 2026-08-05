from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class KnownCondition(BaseModel):
    """A condition the patient is known to have, going into a consultation.

    `source` distinguishes what the doctor asserted from what the system inferred off
    prior consultations, so a derived entry is never mistaken for a confirmed diagnosis.
    """

    name: str
    detail: Optional[str] = None  # e.g. "type 2, on metformin"
    icd_code: Optional[str] = None  # populated once coding exists
    source: str = "doctor"  # "doctor" | "derived"
    first_seen_at: datetime = Field(default_factory=datetime.utcnow)


class Patient(BaseModel):
    patient_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    doctor_id: str
    name: str
    age: int
    gender: Optional[str] = None
    phone: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    # Clinical profile. All defaulted, so patient documents written before this existed
    # still validate. patient_store.update takes **fields, so no store change is needed.
    conditions: list[KnownCondition] = []
    allergies: list[str] = []
    current_medications: list[str] = []
    profile_updated_at: Optional[datetime] = None
