"""Ticketing flow data models.

All timestamps stored as UTC. IST formatting only at the API response boundary.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field


# ── IST helper ────────────────────────────────────────────────
_IST_OFFSET_HOURS = 5.5  # UTC+5:30


def to_ist_str(dt: Optional[datetime]) -> Optional[str]:
    """Format a UTC datetime as an IST string for API responses."""
    if dt is None:
        return None
    from datetime import timedelta
    ist = dt.replace(tzinfo=timezone.utc) + timedelta(hours=_IST_OFFSET_HOURS)
    return ist.strftime("%Y-%m-%d %H:%M:%S IST")


# ── Hospital ───────────────────────────────────────────────────

class Hospital(BaseModel):
    hospital_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    slug: str  # unique, URL-facing
    name: str
    default_language: str = "hi"  # Hindi default
    created_at: datetime = Field(default_factory=datetime.utcnow)


# ── Category ───────────────────────────────────────────────────

class TicketCategory(BaseModel):
    category_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    hospital_id: str
    key: str   # e.g. "general_medicine", "gynecology"
    label: str  # e.g. "General Medicine", "Gynaecology"
    active: bool = True


# Default seed categories for every new hospital
DEFAULT_CATEGORIES: list[tuple[str, str]] = [
    ("general_medicine", "General Medicine"),
    ("gynecology", "Gynaecology / Obstetrics"),
    ("pediatrics", "Paediatrics"),
    ("orthopedics", "Orthopaedics"),
    ("cardiology", "Cardiology"),
    ("dermatology", "Dermatology"),
    ("ent", "ENT (Ear, Nose, Throat)"),
    ("ophthalmology", "Ophthalmology"),
    ("psychiatry", "Psychiatry / Mental Health"),
    ("gastroenterology", "Gastroenterology"),
    ("neurology", "Neurology"),
    ("urology", "Urology"),
    ("oncology", "Oncology"),
    ("endocrinology", "Endocrinology / Diabetes"),
    ("pulmonology", "Pulmonology / Chest"),
]


# ── Patient ────────────────────────────────────────────────────

class TicketPatient(BaseModel):
    patient_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    phone: str       # globally unique across all hospitals
    name: Optional[str] = None
    age: Optional[int] = None
    gender: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


# ── QA entry (reuse shape from clinical) ──────────────────────

class TicketQAEntry(BaseModel):
    question_id: str
    question_text: str
    answer: str
    timestamp: datetime = Field(default_factory=datetime.utcnow)


# ── Clinical flag (reuse shape from clinical) ─────────────────

class TicketFlag(BaseModel):
    flag_type: str   # CRITICAL_RED_FLAG | RED_FLAG | IMPORTANT | NOTE
    description: str
    raised_at: datetime = Field(default_factory=datetime.utcnow)


# ── Category info stored on session ───────────────────────────

class CategoryInfo(BaseModel):
    key: str
    label: str
    source: Literal["auto", "manual"]


# ── Session ────────────────────────────────────────────────────

class TicketSession(BaseModel):
    session_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    # Human-readable auto-incremented ticket number, e.g. "TKT-000042".
    # Assigned on creation by the session store. Used as the searchable receipt ID.
    ticket_number: Optional[str] = None
    hospital_id: str
    patient_id: str

    phase: Literal["triage", "consultation", "result"] = "triage"
    status: Literal["active", "partial", "completed"] = "active"

    # Soft delete — never hard-delete
    deleted_at: Optional[datetime] = None

    category: Optional[CategoryInfo] = None
    language: str = "hi"   # defaults to hospital default_language
    gender: str = "unknown"

    qa_log: list[TicketQAEntry] = []
    flags: list[TicketFlag] = []
    summary: Optional[Any] = None  # SOAP dict from SummarizationService

    turn_count: int = 0
    started_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    ended_at: Optional[datetime] = None

    # Partial stale timeout (minutes). Checked lazily on read.
    STALE_MINUTES: int = Field(default=30, exclude=True)
