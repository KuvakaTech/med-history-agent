from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from app.core.database import get_db
from app.clinical.patient import Patient


async def create(
    doctor_id: str,
    name: str,
    age: int,
    gender: Optional[str] = None,
    phone: Optional[str] = None,
) -> Patient:
    patient = Patient(doctor_id=doctor_id, name=name, age=age, gender=gender, phone=phone)
    await get_db()["patients"].insert_one(patient.model_dump(mode="json"))
    return patient


async def get(patient_id: str, doctor_id: str) -> Optional[Patient]:
    doc = await get_db()["patients"].find_one(
        {"patient_id": patient_id, "doctor_id": doctor_id}, {"_id": 0}
    )
    return Patient.model_validate(doc) if doc else None


async def list_for_doctor(doctor_id: str) -> list[dict]:
    cursor = (
        get_db()["patients"]
        .find({"doctor_id": doctor_id}, {"_id": 0})
        .sort("created_at", -1)
    )
    return [doc async for doc in cursor]


async def update(patient_id: str, doctor_id: str, **fields) -> Optional[Patient]:
    fields["updated_at"] = datetime.now(timezone.utc)
    result = await get_db()["patients"].find_one_and_update(
        {"patient_id": patient_id, "doctor_id": doctor_id},
        {"$set": fields},
        return_document=True,
        projection={"_id": 0},
    )
    return Patient.model_validate(result) if result else None
