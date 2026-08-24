"""Hospital admin and super-admin endpoints for the ticketing flow.

Role rules:
  hospital_admin  — scoped to their hospital_id (from JWT)
  super_admin     — can pass ?hospital_id= to scope, or omit to see all

Routes:
  GET  /v2/admin/hospitals                  (super_admin)
  POST /v2/admin/hospitals                  (super_admin)
  GET  /v2/admin/stats                      (hospital_admin | super_admin)
  GET  /v2/admin/sessions                   (hospital_admin | super_admin)
  GET  /v2/admin/sessions/{id}              (hospital_admin | super_admin)
  GET  /v2/admin/categories                 (hospital_admin | super_admin)
  POST /v2/admin/categories                 (hospital_admin | super_admin)
  PATCH /v2/admin/categories/{id}           (hospital_admin | super_admin)
  GET  /v2/admin/users                      (super_admin)
  POST /v2/admin/users                      (super_admin) — create hospital_admin account
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, EmailStr, field_validator

from app.auth import user_store
from app.auth.deps import require_hospital_admin, require_super_admin
from app.ticketing.hospital_store import hospital_store
from app.ticketing.models import Hospital, TicketCategory, to_ist_str
from app.ticketing.patient_store import ticket_patient_store
from app.ticketing.session_store import ticket_session_store

router = APIRouter()
log = logging.getLogger(__name__)


# ── Request models ────────────────────────────────────────────

class CreateHospitalRequest(BaseModel):
    slug: str
    name: str
    default_language: str = "hi"


class CreateAdminUserRequest(BaseModel):
    email: EmailStr
    name: str
    password: str
    role: Literal["hospital_admin", "super_admin"] = "hospital_admin"
    hospital_id: Optional[str] = None   # required when role == hospital_admin

    @field_validator("password")
    @classmethod
    def strong_enough(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError("Password must be at least 8 characters.")
        return v


class CreateCategoryRequest(BaseModel):
    key: str
    label: str


class UpdateCategoryRequest(BaseModel):
    label: Optional[str] = None
    active: Optional[bool] = None


# ── Helpers ───────────────────────────────────────────────────

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
    s["ended_at_ist"]   = to_ist_str(_parse_dt(s.get("ended_at")))
    s["deleted_at_ist"] = to_ist_str(_parse_dt(s.get("deleted_at")))
    return s


def _resolve_hid(user: dict, hospital_id_param: Optional[str]) -> str:
    """Get hospital_id — from JWT for hospital_admin, from query param for super_admin."""
    hid = user.get("hospital_id") or hospital_id_param
    if not hid:
        raise HTTPException(
            status_code=400,
            detail="Provide ?hospital_id= to scope the request (required for super_admin).",
        )
    return hid


# ── Hospital endpoints (super_admin) ──────────────────────────

@router.get("/hospitals")
async def list_hospitals(user: dict = Depends(require_super_admin)):
    return {"hospitals": await hospital_store.list_all()}


@router.post("/hospitals", status_code=201)
async def create_hospital(
    body: CreateHospitalRequest,
    user: dict = Depends(require_super_admin),
):
    slug = body.slug.strip().lower().replace(" ", "-")
    if await hospital_store.get_by_slug(slug):
        raise HTTPException(status_code=409, detail=f"Slug '{slug}' already in use.")
    hospital = Hospital(
        slug=slug,
        name=body.name.strip(),
        default_language=body.default_language,
    )
    await hospital_store.create(hospital)
    return hospital.model_dump(mode="json")


# ── Admin user management (super_admin) ───────────────────────

@router.get("/users")
async def list_admin_users(
    hospital_id: Optional[str] = Query(None),
    user: dict = Depends(require_super_admin),
):
    """List all hospital_admin and super_admin accounts."""
    admins = await user_store.list_admins(hospital_id=hospital_id)
    return {"users": admins}


@router.post("/users", status_code=201)
async def create_admin_user(
    body: CreateAdminUserRequest,
    user: dict = Depends(require_super_admin),
):
    """Create a hospital_admin or super_admin account."""
    if body.role == "hospital_admin" and not body.hospital_id:
        raise HTTPException(
            status_code=422,
            detail="hospital_id is required when creating a hospital_admin.",
        )
    if body.hospital_id:
        hospital = await hospital_store.get(body.hospital_id)
        if not hospital:
            raise HTTPException(status_code=404, detail="Hospital not found.")

    hashed = user_store.hash_password(body.password)
    try:
        new_user = await user_store.create_admin(
            email=body.email,
            name=body.name.strip(),
            hashed_password=hashed,
            role=body.role,
            hospital_id=body.hospital_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))

    return {
        "id": str(new_user["_id"]),
        "email": new_user["email"],
        "name": new_user["name"],
        "role": new_user["role"],
        "hospital_id": new_user.get("hospital_id"),
    }


# ── Stats endpoint ────────────────────────────────────────────

@router.get("/stats")
async def get_stats(
    hospital_id: Optional[str] = Query(None),
    user: dict = Depends(require_hospital_admin),
):
    """Dashboard stats for a hospital: today's sessions broken down by status,
    plus a running count of sessions with critical flags."""
    hid = _resolve_hid(user, hospital_id)

    # All sessions for this hospital (last 500, enough for stats)
    all_sessions = await ticket_session_store.list_for_hospital(
        hospital_id=hid, limit=500, include_deleted=False
    )

    # Today in IST (UTC+5:30)
    now_utc = datetime.utcnow()
    ist_offset = timedelta(hours=5, minutes=30)
    today_ist = (now_utc + ist_offset).date()

    def _session_date_ist(s: dict):
        dt = _parse_dt(s.get("started_at"))
        if dt is None:
            return None
        return (dt + ist_offset).date()

    today_sessions = [s for s in all_sessions if _session_date_ist(s) == today_ist]

    total_today        = len(today_sessions)
    completed_today    = sum(1 for s in today_sessions if s.get("status") == "completed")
    partial_today      = sum(1 for s in today_sessions if s.get("status") == "partial")
    active_today       = sum(1 for s in today_sessions if s.get("status") == "active")
    critical_today     = sum(
        1 for s in today_sessions
        if any(f.get("flag_type") == "CRITICAL_RED_FLAG" for f in (s.get("flags") or []))
    )

    total_all          = len(all_sessions)
    critical_all       = sum(
        1 for s in all_sessions
        if any(f.get("flag_type") == "CRITICAL_RED_FLAG" for f in (s.get("flags") or []))
    )

    return {
        "date_ist": str(today_ist),
        "today": {
            "total":     total_today,
            "completed": completed_today,
            "partial":   partial_today,
            "active":    active_today,
            "critical":  critical_today,
        },
        "all_time": {
            "total":    total_all,
            "critical": critical_all,
        },
    }


# ── Session endpoints ─────────────────────────────────────────

@router.get("/sessions")
async def list_sessions(
    hospital_id: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    category: Optional[str] = Query(None),
    ticket: Optional[str] = Query(None, description="Exact ticket number, e.g. TKT-000042"),
    include_deleted: bool = Query(False),
    date_from: Optional[str] = Query(None, description="ISO date, e.g. 2026-08-01"),
    date_to:   Optional[str] = Query(None, description="ISO date, e.g. 2026-08-31"),
    limit: int = Query(100, ge=1, le=500),
    user: dict = Depends(require_hospital_admin),
):
    hid = _resolve_hid(user, hospital_id)

    sessions = await ticket_session_store.list_for_hospital(
        hospital_id=hid,
        limit=limit,
        status=status,
        category_key=category,
        include_deleted=include_deleted,
        search_ticket=ticket,
    )

    # Date range filter — done in Python after fetch (avoids Mongo query complexity)
    if date_from or date_to:
        ist_offset = timedelta(hours=5, minutes=30)
        try:
            from_date = datetime.fromisoformat(date_from).date() if date_from else None
            to_date   = datetime.fromisoformat(date_to).date()   if date_to   else None
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
    hospital_id: Optional[str] = Query(None),
    user: dict = Depends(require_hospital_admin),
):
    hid = _resolve_hid(user, hospital_id)

    session = await ticket_session_store.get(session_id, hospital_id=hid)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found.")

    patient = await ticket_patient_store.get(session.patient_id)
    patient_info = patient.model_dump(mode="json") if patient else None

    doc = session.model_dump(mode="json")
    doc["started_at_ist"] = to_ist_str(session.started_at)
    doc["ended_at_ist"]   = to_ist_str(session.ended_at)
    doc["deleted_at_ist"] = to_ist_str(session.deleted_at)
    doc["patient"] = patient_info
    return doc


# ── Category endpoints ────────────────────────────────────────

@router.get("/categories")
async def list_categories(
    hospital_id: Optional[str] = Query(None),
    include_inactive: bool = Query(False),
    user: dict = Depends(require_hospital_admin),
):
    hid = _resolve_hid(user, hospital_id)
    cats = await hospital_store.list_categories(hid, active_only=not include_inactive)
    return {"categories": [c.model_dump(mode="json") for c in cats]}


@router.post("/categories", status_code=201)
async def create_category(
    body: CreateCategoryRequest,
    hospital_id: Optional[str] = Query(None),
    user: dict = Depends(require_hospital_admin),
):
    hid = _resolve_hid(user, hospital_id)
    cat = TicketCategory(
        hospital_id=hid,
        key=body.key.strip().lower(),
        label=body.label.strip(),
        active=True,
    )
    await hospital_store.create_category(cat)
    return cat.model_dump(mode="json")


@router.patch("/categories/{category_id}")
async def update_category(
    category_id: str,
    body: UpdateCategoryRequest,
    hospital_id: Optional[str] = Query(None),
    user: dict = Depends(require_hospital_admin),
):
    hid = _resolve_hid(user, hospital_id)
    updates = body.model_dump(exclude_none=True)
    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update.")
    cat = await hospital_store.update_category(category_id, hid, **updates)
    if not cat:
        raise HTTPException(status_code=404, detail="Category not found.")
    return cat.model_dump(mode="json")
