"""Cabin consultation endpoints — live doctor-led multi-speaker consult.

HTTP: create/inspect/delete a cabin session. WS: the live audio + analysis loop,
handled by CabinLiveSession (app/cabin/live.py).
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, WebSocket
from pydantic import BaseModel, ValidationError

from app.auth.deps import verify_token, verify_ws_token
from app.cabin import leases
from app.cabin.live import CabinLiveSession
from app.cabin.models import (
    CabinOverride,
    CabinSession,
    ClinicalPanel,
    LiveSuggestions,
    Utterance,
)
from app.cabin.store import cabin_session_store
from app.clinical.context import Specialty
from app.core.config import settings
from app.storage import r2

router = APIRouter()
log = logging.getLogger(__name__)

# Identity, ownership, consent and the audit trail itself are not correctable by an
# override — rewriting any of them would break tenancy scoping or destroy the record of
# what was changed.
_PROTECTED_FIELDS = {
    "session_id",
    "doctor_id",
    "consent_captured_at",
    "overrides",
    "cost",
    "audio_key",
    "created_at",
}


def _jsonable(value):
    """Pydantic models don't serialise into a Mongo document as-is."""
    return value.model_dump(mode="json") if hasattr(value, "model_dump") else value


class CreateCabinSessionRequest(BaseModel):
    specialty: Specialty
    patient_id: Optional[str] = None
    patient_name: Optional[str] = None
    consent: (
        bool  # DPDP Act 2023 — must be explicitly true before any audio is accepted
    )


class CabinSessionResponse(BaseModel):
    session_id: str
    status: str
    specialty: str
    consent_captured_at: Optional[datetime] = None


class CabinRecordResponse(BaseModel):
    """The full clinical record of a consultation. Separate from CabinSessionResponse,
    which stays the lightweight create/summary shape other callers already depend on."""

    session_id: str
    doctor_id: str
    patient_id: Optional[str] = None
    patient_name: Optional[str] = None
    specialty: str
    status: str
    workflow: str
    created_at: datetime
    ended_at: Optional[datetime] = None
    consent_captured_at: Optional[datetime] = None
    utterances: list[Utterance] = []
    panel: Optional[ClinicalPanel] = None
    suggestions: Optional[LiveSuggestions] = None
    # `cost` is deliberately absent: it is LLM unit economics, not clinical data, and
    # docs/07-frontend-handoff-phase-1_5.md commits to it never reaching a response model.
    overrides: list[CabinOverride] = []
    stt_warnings: list[str] = []
    roles_verified: bool = False


class OverrideRequest(BaseModel):
    field: str
    value: Any = None
    reason: Optional[str] = None


def _to_response(session: CabinSession) -> CabinSessionResponse:
    return CabinSessionResponse(
        session_id=session.session_id,
        status=session.status,
        specialty=session.specialty.value,
        consent_captured_at=session.consent_captured_at,
    )


@router.post("/", response_model=CabinSessionResponse, status_code=201)
async def create_cabin_session(
    body: CreateCabinSessionRequest, user: dict = Depends(verify_token)
) -> CabinSessionResponse:
    if not body.consent:
        raise HTTPException(
            status_code=400,
            detail="Patient consent must be captured before starting a cabin consultation.",
        )
    session = CabinSession(
        session_id=str(uuid.uuid4()),
        doctor_id=user["sub"],
        patient_id=body.patient_id,
        specialty=body.specialty,
        patient_name=body.patient_name,
        consent_captured_at=datetime.utcnow(),
    )
    await cabin_session_store.create(session)
    return _to_response(session)


@router.get("/")
async def list_cabin_sessions(
    patient_id: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    user: dict = Depends(verify_token),
) -> dict:
    """Consultations for the signed-in doctor, newest first. `patient_id` narrows it to
    one patient — the query behind the profile builder and the patient timeline."""
    if patient_id:
        sessions = await cabin_session_store.list_for_patient(
            patient_id, user["sub"], limit=limit
        )
    else:
        sessions = await cabin_session_store.list_for_doctor(user["sub"], limit=limit)
    return {"sessions": sessions}


@router.get("/{session_id}/record", response_model=CabinRecordResponse)
async def get_cabin_record(
    session_id: str, user: dict = Depends(verify_token)
) -> CabinRecordResponse:
    """The full clinical record. Everything downstream — coding, prescription, claims —
    reads through here."""
    session = await cabin_session_store.get(session_id, doctor_id=user["sub"])
    if not session:
        raise HTTPException(status_code=404, detail="Session not found.")
    return CabinRecordResponse(
        **session.model_dump(exclude={"specialty", "workflow", "audio_key", "cost"}),
        specialty=session.specialty.value,
        workflow=session.workflow.value,
    )


@router.post("/{session_id}/override")
async def override_cabin_record(
    session_id: str, body: OverrideRequest, user: dict = Depends(verify_token)
):
    """Doctor correction to a finished record, with an audit entry.

    The change is validated on a copy before it is committed, which is why CabinSession
    deliberately does *not* set validate_assignment the way ConsultationContext does.
    The reason is correctness, not speed: with it on, the plain setattrs in
    CabinLiveSession._teardown (status, ended_at, audio_key, cost) could raise, and that
    path has no try/except — a raise there would skip the final reconciliation, the
    flush, and the "ended" frame. Adding an exception path to teardown to protect an
    endpoint is the wrong trade. Validating at this boundary gives the same anti-bricking
    property and a better error message.
    """
    session = await cabin_session_store.get(session_id, doctor_id=user["sub"])
    if not session:
        raise HTTPException(status_code=404, detail="Session not found.")
    if session.status == "active":
        # CabinLiveSession holds the panel in memory and _flush overwrites the stored
        # document every 15s, so an override applied now would be silently discarded.
        raise HTTPException(
            status_code=409,
            detail="This consultation is still live. Corrections can be made once it ends.",
        )
    if not hasattr(session, body.field) or body.field in _PROTECTED_FIELDS:
        raise HTTPException(
            status_code=422, detail=f"Field '{body.field}' cannot be overridden."
        )

    original = getattr(session, body.field, None)
    candidate = session.model_copy(deep=True)
    setattr(candidate, body.field, body.value)
    try:
        validated = CabinSession.model_validate(candidate.model_dump(mode="json"))
    except ValidationError as exc:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid value for '{body.field}': {exc.errors()[0]['msg']}",
        )

    validated.overrides = list(session.overrides) + [
        CabinOverride(
            field=body.field,
            original_value=_jsonable(original),
            overridden_value=body.value,
            reason=body.reason,
            doctor_id=user["sub"],
        )
    ]
    await cabin_session_store.update(validated)
    return {"overridden": body.field, "new_value": body.value}


@router.get("/{session_id}", response_model=CabinSessionResponse)
async def get_cabin_session(
    session_id: str, user: dict = Depends(verify_token)
) -> CabinSessionResponse:
    session = await cabin_session_store.get(session_id, doctor_id=user["sub"])
    if not session:
        raise HTTPException(status_code=404, detail="Session not found.")
    return _to_response(session)


@router.delete("/{session_id}")
async def delete_cabin_session(session_id: str, user: dict = Depends(verify_token)):
    session = await cabin_session_store.get(session_id, doctor_id=user["sub"])
    if not session:
        raise HTTPException(status_code=404, detail="Session not found.")
    if session.audio_key:
        try:
            await r2.delete_audio(session.audio_key)
        except Exception as exc:
            log.warning(
                "Failed to delete cabin audio %s for session %s: %s",
                session.audio_key,
                session_id,
                exc,
            )
    await cabin_session_store.delete(session_id)
    return {"deleted": session_id}


@router.websocket("/{session_id}/stream")
async def cabin_stream(
    websocket: WebSocket,
    session_id: str,
    user: dict = Depends(verify_ws_token),
) -> None:
    await websocket.accept()

    session = await cabin_session_store.get(session_id, doctor_id=user["sub"])
    if not session:
        await websocket.send_json(
            {
                "type": "error",
                "fatal": True,
                "code": "session_not_found",
                "message": "Session not found",
            }
        )
        await websocket.close(code=1008)
        return

    # Checked before acquiring, so a refused connection never takes a lease. Checked
    # after the ownership lookup above, so a doctor at the cap passing an unknown
    # session_id still gets "not found" rather than a misleading limit message.
    limit = settings.CABIN_MAX_CONCURRENT_SESSIONS_PER_DOCTOR
    if await leases.active_count(user["sub"]) >= limit:
        await websocket.send_json(
            {
                "type": "error",
                "fatal": True,
                "code": "session_limit",
                "limit": limit,
                "message": (
                    "Too many consultations are open on this account. "
                    "Close one and try again."
                ),
            }
        )
        # 4029 rather than 1008: the client has to tell "too many open, retry later"
        # apart from "this consultation is gone" without string-matching the message.
        await websocket.close(code=4029)
        return

    if not await leases.acquire(session_id, user["sub"]):
        await websocket.send_json(
            {
                "type": "error",
                "fatal": True,
                "code": "duplicate_connection",
                "message": "This consultation already has an active connection.",
            }
        )
        await websocket.close(code=1008)
        return

    try:
        live_session = CabinLiveSession(session, websocket)
        await live_session.run()
    except Exception as exc:
        log.error(
            "cabin stream failed for session %s: %s", session_id, exc, exc_info=True
        )
    finally:
        # Release lives here, not in _teardown: the endpoint acquired it, and this
        # finally also covers run() raising above.
        await leases.release(session_id)
        try:
            await websocket.close()
        except Exception:
            pass
