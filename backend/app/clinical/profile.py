"""Builds the clinical profile a consultation is judged against.

Two sources, deliberately kept distinguishable:

- what the doctor recorded on the patient (`source="doctor"`), and
- what prior consultations imply (`source="derived"`).

The doctor's entry always wins on a name collision. A derived condition is a hint that
the doctor may not have confirmed, and presenting it as though they had would be exactly
the kind of quiet escalation this codebase avoids everywhere else.

This is pure and synchronous — callers fetch the sessions. That keeps it trivially
testable and keeps the Mongo reads at the call site, where their cost is visible.
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel

from app.clinical.patient import KnownCondition, Patient


class PatientProfile(BaseModel):
    patient_id: Optional[str] = None
    age: Optional[int] = None
    gender: Optional[str] = None
    conditions: list[KnownCondition] = []
    allergies: list[str] = []
    current_medications: list[str] = []

    def is_empty(self) -> bool:
        """Nothing worth checking a consultation against — the common case for a
        first-time patient, and the cheapest possible gap-detection outcome."""
        return not (self.conditions or self.allergies or self.current_medications)


def _norm(name: str) -> str:
    return " ".join(name.lower().split())


def _derived_conditions(prior_sessions: list[dict]) -> list[KnownCondition]:
    """Conditions implied by earlier consultations.

    Reads only the reconciled panel of each prior session — the panel is the record the
    pipeline already treats as authoritative, so nothing is re-inferred from raw text.
    """
    found: dict[str, KnownCondition] = {}
    for row in prior_sessions:
        panel = row.get("panel") or {}
        for diagnosis in panel.get("diagnoses") or []:
            name = (diagnosis.get("condition") or "").strip()
            if not name:
                continue
            key = _norm(name)
            if key in found:
                continue
            found[key] = KnownCondition(
                name=name,
                detail=diagnosis.get("reasoning"),
                icd_code=diagnosis.get("icd_code"),
                source="derived",
            )
    return list(found.values())


def build_profile(
    patient: Optional[Patient], prior_sessions: Optional[list[dict]] = None
) -> PatientProfile:
    """Merge the doctor-maintained record with what prior consultations imply."""
    if patient is None:
        return PatientProfile()

    conditions = list(patient.conditions)
    claimed = {_norm(c.name) for c in conditions}
    for derived in _derived_conditions(prior_sessions or []):
        if _norm(derived.name) not in claimed:
            conditions.append(derived)
            claimed.add(_norm(derived.name))

    return PatientProfile(
        patient_id=patient.patient_id,
        age=patient.age,
        gender=patient.gender,
        conditions=conditions,
        allergies=list(patient.allergies),
        current_medications=list(patient.current_medications),
    )
