"""Public kiosk endpoints (Jan Sunwai) — no auth."""
from __future__ import annotations

import logging
import uuid
from typing import Optional

from fastapi import APIRouter, HTTPException, WebSocket
from pydantic import BaseModel

from app.core.config import settings
from app.kiosk import events as ev
from app.kiosk.centre_store import centre_store
from app.kiosk.hindi_display import to_devanagari_display
from app.kiosk.models import KioskSession, to_ist_str
from app.kiosk.post_call_extract import format_transcript
from app.kiosk.session_store import kiosk_session_store
from app.kiosk.voice_session import (
    KioskVoiceSession,
    acquire_live_slot,
    release_live_slot,
)

router = APIRouter()
log = logging.getLogger(__name__)


class StartSessionRequest(BaseModel):
    phone: str
    language: Optional[str] = None
    gender: str = "unknown"


class StartSessionResponse(BaseModel):
    session_id: str
    phone: str
    language: str
    phase: str
    status: str


class CentreResponse(BaseModel):
    slug: str
    name: str
    default_language: str


@router.get("/{slug}", response_model=CentreResponse)
async def get_centre(slug: str) -> CentreResponse:
    centre = await centre_store.get_by_slug(slug)
    if not centre:
        raise HTTPException(status_code=404, detail="Kiosk centre not found.")
    return CentreResponse(
        slug=centre.slug,
        name=centre.name,
        default_language=centre.default_language,
    )


class KioskTranscriptLine(BaseModel):
    speaker: str
    text: str


class GrievanceResultResponse(BaseModel):
    session_id: str
    complaint_number: Optional[str] = None
    phase: str
    status: str
    phone: str
    language: str
    gender: str
    grievance: Optional[dict] = None
    full_transcript: Optional[str] = None
    transcript: list[KioskTranscriptLine] = []
    started_at: Optional[str] = None
    ended_at: Optional[str] = None
    centre_name: Optional[str] = None


@router.post("/{slug}/session", response_model=StartSessionResponse, status_code=201)
async def start_session(slug: str, body: StartSessionRequest) -> StartSessionResponse:
    centre = await centre_store.get_by_slug(slug)
    if not centre:
        raise HTTPException(status_code=404, detail="Kiosk centre not found.")

    phone = body.phone.strip()
    if not phone:
        raise HTTPException(status_code=422, detail="Phone number is required.")

    language = (body.language or centre.default_language).strip().lower()

    session = KioskSession(
        session_id=str(uuid.uuid4()),
        centre_id=centre.centre_id,
        phone=phone,
        language=language,
        gender=body.gender,
        phase="complaint",
        status="active",
    )
    await kiosk_session_store.create(session)

    return StartSessionResponse(
        session_id=session.session_id,
        phone=phone,
        language=language,
        phase=session.phase,
        status=session.status,
    )


@router.get("/{slug}/session/{session_id}/result", response_model=GrievanceResultResponse)
async def get_session_result(slug: str, session_id: str) -> GrievanceResultResponse:
    centre = await centre_store.get_by_slug(slug)
    if not centre:
        raise HTTPException(status_code=404, detail="Kiosk centre not found.")

    session = await kiosk_session_store.get(session_id, centre_id=centre.centre_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found.")
    if session.deleted_at is not None:
        raise HTTPException(status_code=404, detail="Session not found.")

    grievance = (
        session.grievance.model_dump(mode="json") if session.grievance else None
    )
    transcript_lines = [
        KioskTranscriptLine(
            speaker=e.speaker,
            text=to_devanagari_display(e.text),
        )
        for e in session.transcript
        if (e.text or "").strip()
    ]
    full_transcript = format_transcript(session.transcript).strip() or None
    if full_transcript:
        full_transcript = "\n".join(
            f"{'आप' if line.speaker == 'user' else 'AI सहायक'}: {line.text}"
            for line in transcript_lines
        )

    return GrievanceResultResponse(
        session_id=session.session_id,
        complaint_number=session.complaint_number,
        phase=session.phase,
        status=session.status,
        phone=session.phone,
        language=session.language,
        gender=session.gender,
        grievance=grievance,
        full_transcript=full_transcript,
        transcript=transcript_lines,
        started_at=to_ist_str(session.started_at),
        ended_at=to_ist_str(session.ended_at),
        centre_name=centre.name,
    )


@router.post("/{slug}/session/{session_id}/discard")
async def discard_session(slug: str, session_id: str):
    centre = await centre_store.get_by_slug(slug)
    if not centre:
        raise HTTPException(status_code=404, detail="Kiosk centre not found.")

    ok = await kiosk_session_store.soft_delete(session_id, centre.centre_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Session not found.")
    return {"discarded": session_id}


@router.websocket("/{slug}/session/{session_id}/voice")
async def voice_stream(ws: WebSocket, slug: str, session_id: str) -> None:
    await ws.accept()

    centre = await centre_store.get_by_slug(slug)
    if not centre:
        await ws.send_json(
            {"type": "error", "fatal": True, "message": "Kiosk centre not found."}
        )
        await ws.close(code=1008)
        return

    session = await kiosk_session_store.get(session_id, centre_id=centre.centre_id)
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

    try:
        if not await acquire_live_slot(centre.centre_id):
            await ws.send_json(
                ev.error(
                    "सभी कियोस्क लाइन व्यस्त हैं। कृपया कुछ क्षण बाद दोबारा प्रयास करें।",
                    fatal=True,
                )
            )
            await ws.close(code=1013)
            return
        try:
            voice = KioskVoiceSession(session=session, ws=ws, centre=centre)
            await voice.run()
        finally:
            await release_live_slot(centre.centre_id)
    except Exception as exc:
        log.error(
            "kiosk voice_stream failed for %s: %s", session_id, exc, exc_info=True
        )
    finally:
        try:
            await ws.close()
        except Exception:
            pass
