from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.auth.deps import verify_token
from app.clinical import patient_store
from app.clinical.session_store import session_store

router = APIRouter(prefix="/patients", tags=["patients"])


class CreatePatientRequest(BaseModel):
    name: str
    age: int
    gender: Optional[str] = None
    phone: Optional[str] = None


class UpdatePatientRequest(BaseModel):
    name: Optional[str] = None
    age: Optional[int] = None
    gender: Optional[str] = None
    phone: Optional[str] = None


@router.post("", status_code=201)
async def create_patient(
    body: CreatePatientRequest, user: dict = Depends(verify_token)
):
    patient = await patient_store.create(
        doctor_id=user["sub"],
        name=body.name.strip(),
        age=body.age,
        gender=body.gender,
        phone=body.phone,
    )
    return patient.model_dump(mode="json")


@router.get("")
async def list_patients(user: dict = Depends(verify_token)):
    patients = await patient_store.list_for_doctor(doctor_id=user["sub"])
    return {"patients": patients}


@router.get("/{patient_id}")
async def get_patient(patient_id: str, user: dict = Depends(verify_token)):
    patient = await patient_store.get(patient_id=patient_id, doctor_id=user["sub"])
    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found.")
    return patient.model_dump(mode="json")


@router.get("/{patient_id}/history")
async def get_patient_history(patient_id: str, user: dict = Depends(verify_token)):
    patient = await patient_store.get(patient_id=patient_id, doctor_id=user["sub"])
    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found.")
    sessions = await session_store.list_for_patient(
        patient_id=patient_id, doctor_id=user["sub"]
    )
    return {"patient": patient.model_dump(mode="json"), "sessions": sessions}


@router.patch("/{patient_id}")
async def update_patient(
    patient_id: str, body: UpdatePatientRequest, user: dict = Depends(verify_token)
):
    updates = body.model_dump(exclude_none=True)
    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update.")
    patient = await patient_store.update(
        patient_id=patient_id, doctor_id=user["sub"], **updates
    )
    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found.")
    return patient.model_dump(mode="json")
