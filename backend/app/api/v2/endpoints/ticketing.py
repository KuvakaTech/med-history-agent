"""Patient-facing ticketing endpoints.

Unlock is PIN-gated; session/voice/result/discard require a kiosk JWT.

Routes:
  GET  /v2/t/{slug}/config                 — public kiosk settings (collect_caste)
  POST /v2/t/{slug}/unlock                — PIN unlock → kiosk JWT
  POST /v2/t/{slug}/session                — create session (phone, language, gender, caste)
  WS   /v2/t/{slug}/session/{id}/voice     — continuous voice call (?token=)
  GET  /v2/t/{slug}/session/{id}/result    — fetch result (summary + flags + ticket_number)
  POST /v2/t/{slug}/session/{id}/discard   — soft-delete
"""

from __future__ import annotations

import logging
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, WebSocket
from pydantic import BaseModel

from app.auth.deps import make_kiosk_token, parse_kiosk_token, require_kiosk_token
from app.core.config import settings
from app.ticketing import events as ev
from app.ticketing.hospital_store import hospital_store
from app.ticketing.models import CASTE_VALUES, VISIT_TYPE_VALUES, TicketSession, hospital_public_dict, to_ist_str
from app.ticketing.patient_store import ticket_patient_store
from app.ticketing.session_store import ticket_session_store
from app.ticketing.voice_session import TicketVoiceSession

router = APIRouter()
log = logging.getLogger(__name__)


# ── Request / Response models ─────────────────────────────────


class StartSessionRequest(BaseModel):
    phone: str
    language: Optional[str] = None  # defaults to hospital.default_language
    visit_type: str
    gender: str = "unknown"
    caste: Optional[str] = None  # required when hospital.collect_caste


class StartSessionResponse(BaseModel):
    session_id: str
    ticket_number: Optional[str] = None
    opd_number: Optional[int] = None
    patient_id: str
    language: str
    phase: str
    status: str


class PatientInfo(BaseModel):
    patient_id: str
    name: Optional[str] = None
    age: Optional[int] = None
    gender: Optional[str] = None
    caste: Optional[str] = None
    address: Optional[str] = None
    guardian_name: Optional[str] = None
    phone: str


class UnlockRequest(BaseModel):
    pin: str


class UnlockResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    hospital_name: str
    collect_caste: bool = False


class HospitalConfigResponse(BaseModel):
    slug: str
    name: str
    collect_caste: bool = False
    has_kiosk_pin: bool = False


class SessionResultResponse(BaseModel):
    session_id: str
    ticket_number: Optional[str] = None  # human-readable receipt ID, e.g. TKT-000042
    opd_number: Optional[int] = None
    opd_date_ist: Optional[str] = None  # YYYY-MM-DD IST visit date
    visit_type: Optional[str] = None
    collect_caste: bool = False
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


@router.get("/{slug}/config", response_model=HospitalConfigResponse)
async def hospital_config(slug: str) -> HospitalConfigResponse:
    hospital = await hospital_store.get_by_slug(slug)
    if not hospital:
        raise HTTPException(status_code=404, detail="Hospital not found.")
    public = hospital_public_dict(hospital)
    return HospitalConfigResponse(
        slug=hospital.slug,
        name=hospital.name,
        collect_caste=bool(public.get("collect_caste")),
        has_kiosk_pin=bool(public.get("has_kiosk_pin")),
    )


@router.post("/{slug}/unlock", response_model=UnlockResponse)
async def unlock_kiosk(slug: str, payload: UnlockRequest) -> UnlockResponse:
    # No @limiter.limit here: slowapi's decorator breaks FastAPI JSON-body binding on
    # Python 3.12 when the route also has a path param. SlowAPIMiddleware still applies
    # RATE_LIMIT_DEFAULT; PIN brute-force is also bounded by bcrypt verification cost.
    hospital = await hospital_store.get_by_slug(slug)
    if not hospital:
        raise HTTPException(status_code=404, detail="Hospital not found.")
    if not hospital.kiosk_pin_hash:
        raise HTTPException(status_code=409, detail="Kiosk PIN is not configured.")
    if not hospital_store.verify_kiosk_pin(hospital, payload.pin.strip()):
        raise HTTPException(status_code=401, detail="Invalid PIN.")

    token = make_kiosk_token(hospital_id=hospital.hospital_id, slug=hospital.slug)
    return UnlockResponse(
        access_token=token,
        expires_in=settings.TICKETING_KIOSK_TOKEN_HOURS * 3600,
        hospital_name=hospital.name,
        collect_caste=hospital.collect_caste,
    )


@router.post("/{slug}/session", response_model=StartSessionResponse, status_code=201)
async def start_session(
    slug: str,
    body: StartSessionRequest,
    kiosk: dict = Depends(require_kiosk_token),
) -> StartSessionResponse:
    hospital = await hospital_store.get_by_slug(slug)
    if not hospital:
        raise HTTPException(status_code=404, detail="Hospital not found.")

    phone = body.phone.strip()
    if not phone:
        raise HTTPException(status_code=422, detail="Phone number is required.")

    if kiosk.get("hospital_id") != hospital.hospital_id:
        raise HTTPException(status_code=403, detail="Token does not match this hospital.")

    language = (body.language or hospital.default_language).strip().lower()

    visit_type = body.visit_type.strip().lower()
    if visit_type not in VISIT_TYPE_VALUES:
        raise HTTPException(status_code=422, detail="Visit type is required (opd or ipd).")

    caste: Optional[str] = None
    if hospital.collect_caste:
        raw = (body.caste or "").strip().lower()
        if raw not in CASTE_VALUES:
            raise HTTPException(status_code=422, detail="Caste is required.")
        caste = raw

    # Upsert patient by phone — globally unique, no hospital scoping
    patient = await ticket_patient_store.upsert(
        phone=phone,
        gender=body.gender if body.gender != "unknown" else None,
        caste=caste,
    )

    session = TicketSession(
        session_id=str(uuid.uuid4()),
        hospital_id=hospital.hospital_id,
        patient_id=patient.patient_id,
        language=language,
        gender=body.gender,
        visit_type=visit_type,
        caste=caste,
        phase="triage",
        status="active",
    )
    # ticket_number is assigned inside create()
    await ticket_session_store.create(session)

    return StartSessionResponse(
        session_id=session.session_id,
        ticket_number=session.ticket_number,
        opd_number=session.opd_number,
        patient_id=patient.patient_id,
        language=language,
        phase=session.phase,
        status=session.status,
    )


@router.get("/{slug}/session/{session_id}/result", response_model=SessionResultResponse)
async def get_session_result(
    slug: str,
    session_id: str,
    kiosk: dict = Depends(require_kiosk_token),
) -> SessionResultResponse:
    hospital = await hospital_store.get_by_slug(slug)
    if not hospital:
        raise HTTPException(status_code=404, detail="Hospital not found.")
    if kiosk.get("hospital_id") != hospital.hospital_id:
        raise HTTPException(status_code=403, detail="Token does not match this hospital.")

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
            caste=patient.caste or session.caste,
            address=session.address or patient.address,
            guardian_name=session.guardian_name or patient.guardian_name,
            phone=patient.phone,
        )

    started_ist = to_ist_str(session.started_at)
    return SessionResultResponse(
        session_id=session.session_id,
        ticket_number=session.ticket_number,
        opd_number=session.opd_number,
        opd_date_ist=started_ist[:10] if started_ist else None,
        visit_type=session.visit_type,
        collect_caste=hospital.collect_caste,
        phase=session.phase,
        status=session.status,
        category=session.category.model_dump() if session.category else None,
        flags=[f.model_dump(mode="json") for f in session.flags],
        summary=session.summary,
        started_at=started_ist,
        ended_at=to_ist_str(session.ended_at),
        patient=patient_info,
        hospital_name=hospital.name,
    )


@router.post("/{slug}/session/{session_id}/discard")
async def discard_session(
    slug: str,
    session_id: str,
    kiosk: dict = Depends(require_kiosk_token),
):
    hospital = await hospital_store.get_by_slug(slug)
    if not hospital:
        raise HTTPException(status_code=404, detail="Hospital not found.")
    if kiosk.get("hospital_id") != hospital.hospital_id:
        raise HTTPException(status_code=403, detail="Token does not match this hospital.")

    ok = await ticket_session_store.soft_delete(session_id, hospital.hospital_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Session not found.")
    return {"discarded": session_id}


@router.websocket("/{slug}/session/{session_id}/voice")
async def voice_stream(
    ws: WebSocket,
    slug: str,
    session_id: str,
    token: str = Query(..., description="Kiosk JWT"),
) -> None:
    await ws.accept()

    try:
        parse_kiosk_token(token, slug)
    except HTTPException as exc:
        await ws.send_json(
            {"type": "error", "fatal": True, "message": exc.detail}
        )
        await ws.close(code=1008)
        return

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
