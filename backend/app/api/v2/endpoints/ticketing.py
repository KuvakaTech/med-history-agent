"""Public patient-facing ticketing endpoints (no auth required).

Routes:
  POST /v2/t/{slug}/session              — create session (phone, language, gender)
  WS   /v2/t/{slug}/session/{id}/voice   — continuous voice call
  GET  /v2/t/{slug}/session/{id}/result  — fetch result (summary + flags + ticket_number)
  POST /v2/t/{slug}/session/{id}/discard — soft-delete
"""

from __future__ import annotations

import logging
import uuid
from typing import Optional

from fastapi import APIRouter, HTTPException, WebSocket
from pydantic import BaseModel

from app.core.config import settings
from app.ticketing import events as ev
from app.ticketing.hospital_store import hospital_store
from app.ticketing.models import TicketSession, to_ist_str
from app.ticketing.patient_store import ticket_patient_store
from app.ticketing.session_store import ticket_session_store
from app.ticketing.voice_session import TicketVoiceSession

router = APIRouter()
log = logging.getLogger(__name__)


# ── Request / Response models ─────────────────────────────────


class StartSessionRequest(BaseModel):
    phone: str
    language: Optional[str] = None  # defaults to hospital.default_language
    gender: str = "unknown"


class StartSessionResponse(BaseModel):
    session_id: str
    ticket_number: Optional[str] = None
    patient_id: str
    language: str
    phase: str
    status: str


class PatientInfo(BaseModel):
    patient_id: str
    name: Optional[str] = None
    age: Optional[int] = None
    gender: Optional[str] = None
    phone: str


class SessionResultResponse(BaseModel):
    session_id: str
    ticket_number: Optional[str] = None  # human-readable receipt ID, e.g. TKT-000042
    phase: str
    status: str
    category: Optional[dict] = None
    flags: list[dict] = []
    summary: Optional[dict] = None
    started_at: Optional[str] = None  # IST formatted
    ended_at: Optional[str] = None  # IST formatted
    patient: Optional[PatientInfo] = None
    hospital_name: Optional[str] = None


# ── Endpoints ─────────────────────────────────────────────────


@router.post("/{slug}/session", response_model=StartSessionResponse, status_code=201)
async def start_session(slug: str, body: StartSessionRequest) -> StartSessionResponse:
    hospital = await hospital_store.get_by_slug(slug)
    if not hospital:
        raise HTTPException(status_code=404, detail="Hospital not found.")

    phone = body.phone.strip()
    if not phone:
        raise HTTPException(status_code=422, detail="Phone number is required.")

    language = (body.language or hospital.default_language).strip().lower()

    # Upsert patient by phone — globally unique, no hospital scoping
    patient = await ticket_patient_store.upsert(
        phone=phone,
        gender=body.gender if body.gender != "unknown" else None,
    )

    session = TicketSession(
        session_id=str(uuid.uuid4()),
        hospital_id=hospital.hospital_id,
        patient_id=patient.patient_id,
        language=language,
        gender=body.gender,
        phase="triage",
        status="active",
    )
    # ticket_number is assigned inside create()
    await ticket_session_store.create(session)

    return StartSessionResponse(
        session_id=session.session_id,
        ticket_number=session.ticket_number,
        patient_id=patient.patient_id,
        language=language,
        phase=session.phase,
        status=session.status,
    )


@router.get("/{slug}/session/{session_id}/result", response_model=SessionResultResponse)
async def get_session_result(slug: str, session_id: str) -> SessionResultResponse:
    hospital = await hospital_store.get_by_slug(slug)
    if not hospital:
        raise HTTPException(status_code=404, detail="Hospital not found.")

    session = await ticket_session_store.get(
        session_id, hospital_id=hospital.hospital_id
    )
    if not session:
        raise HTTPException(status_code=404, detail="Session not found.")
    if session.deleted_at is not None:
        raise HTTPException(status_code=404, detail="Session not found.")

    patient = await ticket_patient_store.get(session.patient_id)
    patient_info = None
    if patient:
        patient_info = PatientInfo(
            patient_id=patient.patient_id,
            name=patient.name,
            age=patient.age,
            gender=patient.gender,
            phone=patient.phone,
        )

    return SessionResultResponse(
        session_id=session.session_id,
        ticket_number=session.ticket_number,
        phase=session.phase,
        status=session.status,
        category=session.category.model_dump() if session.category else None,
        flags=[f.model_dump(mode="json") for f in session.flags],
        summary=session.summary,
        started_at=to_ist_str(session.started_at),
        ended_at=to_ist_str(session.ended_at),
        patient=patient_info,
        hospital_name=hospital.name,
    )


@router.post("/{slug}/session/{session_id}/discard")
async def discard_session(slug: str, session_id: str):
    hospital = await hospital_store.get_by_slug(slug)
    if not hospital:
        raise HTTPException(status_code=404, detail="Hospital not found.")

    ok = await ticket_session_store.soft_delete(session_id, hospital.hospital_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Session not found.")
    return {"discarded": session_id}


@router.websocket("/{slug}/session/{session_id}/voice")
async def voice_stream(ws: WebSocket, slug: str, session_id: str) -> None:
    await ws.accept()

    hospital = await hospital_store.get_by_slug(slug)
    if not hospital:
        await ws.send_json(
            {"type": "error", "fatal": True, "message": "Hospital not found."}
        )
        await ws.close(code=1008)
        return

    session = await ticket_session_store.get(
        session_id, hospital_id=hospital.hospital_id
    )
    if not session:
        await ws.send_json(
            {"type": "error", "fatal": True, "message": "Session not found."}
        )
        await ws.close(code=1008)
        return

    if session.deleted_at is not None:
        await ws.send_json(
            {"type": "error", "fatal": True, "message": "Session discarded."}
        )
        await ws.close(code=1008)
        return

    if session.status == "completed":
        await ws.send_json(
            {"type": "error", "fatal": True, "message": "Session already completed."}
        )
        await ws.close(code=1008)
        return

    categories = await hospital_store.list_categories(
        hospital.hospital_id, active_only=True
    )

    try:
        if settings.TICKETING_USE_GEMINI_LIVE:
            from app.ticketing.voice_session_v2 import (
                TicketVoiceSessionV2,
                acquire_live_slot,
                release_live_slot,
            )

            if not await acquire_live_slot(hospital.hospital_id):
                await ws.send_json(
                    ev.error(
                        "All consultation lines are busy. Please try again in a moment.",
                        fatal=True,
                    )
                )
                await ws.close(code=1013)
                return
            try:
                voice = TicketVoiceSessionV2(
                    session=session, ws=ws, categories=categories
                )
                await voice.run()
            finally:
                await release_live_slot(hospital.hospital_id)
        else:
            voice = TicketVoiceSession(session=session, ws=ws, categories=categories)
            await voice.run()
    except Exception as exc:
        log.error(
            "voice_stream failed for session %s: %s", session_id, exc, exc_info=True
        )
    finally:
        try:
            await ws.close()
        except Exception:
            pass
