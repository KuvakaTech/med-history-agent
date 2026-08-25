"""Kiosk centre admin and super-admin endpoints.

Role rules:
  centre_admin  — scoped to their centre_id (from JWT)
  super_admin   — pass ?centre_id= to scope list views, or omit on session detail for global lookup
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, EmailStr, field_validator

from app.auth import user_store
from app.auth.deps import require_centre_admin, require_super_admin
from app.kiosk.centre_store import centre_store
from app.kiosk.hindi_display import to_devanagari_display
from app.kiosk.models import KioskCentre, to_ist_str
from app.kiosk.post_call_extract import format_transcript
from app.kiosk.session_store import kiosk_session_store

router = APIRouter()
log = logging.getLogger(__name__)


class CreateCentreRequest(BaseModel):
    slug: str
    name: str
    default_language: str = "hi"
    prompt_file: Optional[str] = None
    complaint_prefix: Optional[str] = None


class CreateKioskAdminUserRequest(BaseModel):
    email: EmailStr
    name: str
    password: str
    role: Literal["centre_admin", "super_admin"] = "centre_admin"
    centre_id: Optional[str] = None

    @field_validator("password")
    @classmethod
    def strong_enough(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError("Password must be at least 8 characters.")
        return v


def _parse_dt(value):
    if value is None:
        return None
    if hasattr(value, "year"):
        return value
    try:
        return datetime.fromisoformat(str(value))
    except Exception:
        return None


def _format_session(s: dict) -> dict:
    s = dict(s)
    s["started_at_ist"] = to_ist_str(_parse_dt(s.get("started_at")))
    s["ended_at_ist"] = to_ist_str(_parse_dt(s.get("ended_at")))
    s["deleted_at_ist"] = to_ist_str(_parse_dt(s.get("deleted_at")))
    grievance = s.get("grievance") or {}
    if isinstance(grievance, dict):
        s["grievance_summary"] = (
            grievance.get("confirmed_summary")
            or grievance.get("verbatim_problem")
            or grievance.get("category")
        )
    return s


def _resolve_cid(user: dict, centre_id_param: Optional[str]) -> str:
    cid = user.get("centre_id") or centre_id_param
    if not cid:
        raise HTTPException(
            status_code=400,
            detail="Provide ?centre_id= to scope the request (required for super_admin).",
        )
    return cid


def _transcript_lines(session) -> list[dict]:
    return [
        {
            "speaker": e.speaker,
            "text": to_devanagari_display(e.text),
        }
        for e in session.transcript
        if (e.text or "").strip()
    ]


@router.get("/centres")
async def list_centres(user: dict = Depends(require_super_admin)):
    return {"centres": await centre_store.list_all()}


@router.post("/centres", status_code=201)
async def create_centre(
    body: CreateCentreRequest,
    user: dict = Depends(require_super_admin),
):
    centre = KioskCentre(
        slug=body.slug.strip().lower(),
        name=body.name.strip(),
        default_language=body.default_language,
        prompt_file=body.prompt_file,
        complaint_prefix=body.complaint_prefix,
    )
    await centre_store.create(centre)
    return centre.model_dump(mode="json")


@router.get("/centre")
async def get_current_centre(
    centre_id: Optional[str] = Query(None),
    user: dict = Depends(require_centre_admin),
):
    cid = _resolve_cid(user, centre_id)
    centre = await centre_store.get(cid)
    if not centre:
        raise HTTPException(status_code=404, detail="Kiosk centre not found.")
    return centre.model_dump(mode="json")


@router.get("/users")
async def list_admin_users(
    centre_id: Optional[str] = Query(None),
    user: dict = Depends(require_super_admin),
):
    admins = await user_store.list_admins(centre_id=centre_id)
    return {"users": admins}


@router.post("/users", status_code=201)
async def create_admin_user(
    body: CreateKioskAdminUserRequest,
    user: dict = Depends(require_super_admin),
):
    if body.role == "centre_admin" and not body.centre_id:
        raise HTTPException(
            status_code=422,
            detail="centre_id is required when creating a centre_admin.",
        )
    if body.centre_id:
        centre = await centre_store.get(body.centre_id)
        if not centre:
            raise HTTPException(status_code=404, detail="Kiosk centre not found.")

    hashed = user_store.hash_password(body.password)
    try:
        new_user = await user_store.create_admin(
            email=body.email,
            name=body.name.strip(),
            hashed_password=hashed,
            role=body.role,
            centre_id=body.centre_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))

    return {
        "id": str(new_user["_id"]),
        "email": new_user["email"],
        "name": new_user["name"],
        "role": new_user["role"],
        "centre_id": new_user.get("centre_id"),
    }


@router.get("/stats")
async def get_stats(
    centre_id: Optional[str] = Query(None),
    user: dict = Depends(require_centre_admin),
):
    cid = _resolve_cid(user, centre_id)
    all_sessions = await kiosk_session_store.list_for_centre(
        centre_id=cid, limit=500, include_deleted=False
    )

    now_utc = datetime.utcnow()
    ist_offset = timedelta(hours=5, minutes=30)
    today_ist = (now_utc + ist_offset).date()

    def _session_date_ist(s: dict):
        dt = _parse_dt(s.get("started_at"))
        if dt is None:
            return None
        return (dt + ist_offset).date()

    today_sessions = [s for s in all_sessions if _session_date_ist(s) == today_ist]

    return {
        "date_ist": str(today_ist),
        "today": {
            "total": len(today_sessions),
            "completed": sum(1 for s in today_sessions if s.get("status") == "completed"),
            "partial": sum(1 for s in today_sessions if s.get("status") == "partial"),
            "active": sum(1 for s in today_sessions if s.get("status") == "active"),
        },
        "all_time": {
            "total": len(all_sessions),
            "completed": sum(1 for s in all_sessions if s.get("status") == "completed"),
        },
    }


@router.get("/sessions")
async def list_sessions(
    centre_id: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    complaint: Optional[str] = Query(None),
    phone: Optional[str] = Query(None),
    include_deleted: bool = Query(False),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    limit: int = Query(100, ge=1, le=500),
    user: dict = Depends(require_centre_admin),
):
    cid = _resolve_cid(user, centre_id)

    sessions = await kiosk_session_store.list_for_centre(
        centre_id=cid,
        limit=limit,
        status=status,
        include_deleted=include_deleted,
        search_complaint=complaint,
        search_phone=phone,
    )

    if date_from or date_to:
        ist_offset = timedelta(hours=5, minutes=30)
        try:
            from_date = datetime.fromisoformat(date_from).date() if date_from else None
            to_date = datetime.fromisoformat(date_to).date() if date_to else None
        except ValueError:
            raise HTTPException(status_code=422, detail="Invalid date format. Use ISO: 2026-08-01")

        def _in_range(s: dict) -> bool:
            dt = _parse_dt(s.get("started_at"))
            if dt is None:
                return False
            d = (dt + ist_offset).date()
            if from_date and d < from_date:
                return False
            if to_date and d > to_date:
                return False
            return True

        sessions = [s for s in sessions if _in_range(s)]

    return {"sessions": [_format_session(s) for s in sessions], "count": len(sessions)}


@router.get("/sessions/{session_id}")
async def get_session_detail(
    session_id: str,
    centre_id: Optional[str] = Query(None),
    user: dict = Depends(require_centre_admin),
):
    cid = user.get("centre_id") or centre_id
    session = await kiosk_session_store.get(session_id, centre_id=cid)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found.")

    centre = await centre_store.get(session.centre_id)
    transcript_lines = _transcript_lines(session)
    full_transcript = format_transcript(session.transcript).strip() or None
    if full_transcript:
        full_transcript = "\n".join(
            f"{'आप' if line['speaker'] == 'user' else 'AI सहायक'}: {line['text']}"
            for line in transcript_lines
        )

    doc = session.model_dump(mode="json")
    doc["started_at_ist"] = to_ist_str(session.started_at)
    doc["ended_at_ist"] = to_ist_str(session.ended_at)
    doc["deleted_at_ist"] = to_ist_str(session.deleted_at)
    doc["centre_name"] = centre.name if centre else None
    doc["transcript"] = transcript_lines
    doc["full_transcript"] = full_transcript
    return doc
