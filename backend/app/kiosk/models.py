"""Kiosk (Jan Sunwai) data models."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field

_IST_OFFSET_HOURS = 5.5


def to_ist_str(dt: Optional[datetime]) -> Optional[str]:
    if dt is None:
        return None
    from datetime import timedelta

    ist = dt.replace(tzinfo=timezone.utc) + timedelta(hours=_IST_OFFSET_HOURS)
    return ist.strftime("%Y-%m-%d %H:%M:%S IST")


class KioskCentre(BaseModel):
    centre_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    slug: str
    name: str
    default_language: str = "hi"
    created_at: datetime = Field(default_factory=datetime.utcnow)


class KioskTranscriptEntry(BaseModel):
    speaker: Literal["user", "agent"]
    text: str
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class GrievanceAddress(BaseModel):
    house: Optional[str] = None
    street: Optional[str] = None
    village_mohalla: Optional[str] = None
    gp_ward: Optional[str] = None
    tehsil: Optional[str] = None
    block: Optional[str] = None
    post_office: Optional[str] = None
    pin_code: Optional[str] = None
    landmark: Optional[str] = None


class GrievanceRecord(BaseModel):
    full_name: Optional[str] = None
    father_guardian_name: Optional[str] = None
    age: Optional[int] = None
    is_senior_citizen: Optional[bool] = None
    is_divyang: Optional[bool] = None
    residential_address: Optional[GrievanceAddress] = None
    complaint_location_same_as_home: Optional[bool] = None
    complaint_address: Optional[GrievanceAddress] = None
    category: Optional[str] = None
    sub_category: Optional[str] = None
    verbatim_problem: Optional[str] = None
    confirmed_summary: Optional[str] = None
    since_when: Optional[str] = None
    affected_count: Optional[str] = None
    prior_action: Optional[str] = None
    desired_outcome: Optional[str] = None
    department_tag: Optional[str] = None
    urgency: Optional[str] = None  # normal | urgent
    sentiment: Optional[str] = None
    has_photos_or_docs: Optional[bool] = None
    optional_email: Optional[str] = None
    category_details: dict[str, Any] = Field(default_factory=dict)


class KioskSession(BaseModel):
    session_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    centre_id: str
    phone: str
    language: str = "hi"
    gender: str = "unknown"
    phase: Literal["complaint", "result"] = "complaint"
    status: Literal["active", "partial", "completed"] = "active"
    complaint_number: Optional[str] = None
    grievance: Optional[GrievanceRecord] = None
    transcript: list[KioskTranscriptEntry] = []
    turn_count: int = 0
    deleted_at: Optional[datetime] = None
    started_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    ended_at: Optional[datetime] = None
