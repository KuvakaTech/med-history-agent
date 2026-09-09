"""Kiosk data models — grievance (Jan Sunwai) and learning (Guddi) centres."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field

_IST_OFFSET_HOURS = 5.5

CentreKind = Literal["grievance", "learning"]
LessonTopic = Literal[
    "Ghar",
    "Khana",
    "Jaanwar",
    "Rang",
    "Ginti",
    "Shareer",
    "Guddi-choose",
]
WordResult = Literal["clear", "emerging", "not_yet"]
LearningMode = Literal["calm", "lively", "extra-gentle", "full-play"]
LearningMood = Literal["happy", "tired", "shy", "excited", "unclear"]
LearningFlag = Literal[
    "none",
    "needs-a-grown-up",
    "very-shy",
    "distress-noted",
]
EngagementLevel = Literal["high", "medium", "low"]

VALID_LESSON_TOPICS: frozenset[str] = frozenset(
    {"Ghar", "Khana", "Jaanwar", "Rang", "Ginti", "Shareer", "Guddi-choose"}
)


def to_ist_str(dt: Optional[datetime]) -> Optional[str]:
    if dt is None:
        return None
    from datetime import timedelta

    ist = dt.replace(tzinfo=timezone.utc) + timedelta(hours=_IST_OFFSET_HOURS)
    return ist.strftime("%Y-%m-%d %H:%M:%S IST")


_SLUG_DEFAULTS: dict[str, dict[str, str]] = {
    "varanasi-jan-sunwai": {
        "prompt_file": "jan_sunwai_system.txt",
        "complaint_prefix": "JS-VNS",
        "centre_kind": "grievance",
    },
    "varanasi-jan-sunwai-v3": {
        "prompt_file": "jan_sunwai_v3_system.txt",
        "complaint_prefix": "JS-VNS",
        "centre_kind": "grievance",
    },
    "barwani-jan-sunwai": {
        "prompt_file": "barwani_jan_sunwai",
        "complaint_prefix": "JS-BWN",
        "centre_kind": "grievance",
    },
    "varanasi-nagar-nigam": {
        "prompt_file": "nagar_nigam_system.txt",
        "complaint_prefix": "NN-VNS",
        "centre_kind": "grievance",
    },
    "barwani-guddi": {
        "prompt_file": "guddi_learning_system.txt",
        "centre_kind": "learning",
    },
}


def defaults_for_slug(slug: str) -> dict[str, str]:
    return _SLUG_DEFAULTS.get(slug, _SLUG_DEFAULTS["varanasi-jan-sunwai"])


class KioskCentre(BaseModel):
    centre_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    slug: str
    name: str
    default_language: str = "hi"
    centre_kind: CentreKind = "grievance"
    prompt_file: Optional[str] = None
    complaint_prefix: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)


def centre_kind_for(centre: KioskCentre) -> CentreKind:
    return centre.centre_kind


def prompt_file_for_centre(centre: KioskCentre) -> str:
    if centre.prompt_file:
        return centre.prompt_file
    return defaults_for_slug(centre.slug)["prompt_file"]


def complaint_prefix_for_centre(centre: KioskCentre) -> str:
    if centre.complaint_prefix:
        return centre.complaint_prefix
    return defaults_for_slug(centre.slug).get("complaint_prefix", "JS-VNS")


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
    session_type: Optional[str] = None  # complaint | information | help_desk | mixed
    print_mode: Optional[str] = None  # application_letter | info_sheet | none
    print_document_text: Optional[str] = None
    primary_intent: Optional[str] = None
    addressed_to: Optional[dict[str, Any]] = None
    documents_to_attach_or_required: list[str] = Field(default_factory=list)
    out_of_scope: Optional[bool] = None
    flags: list[str] = Field(default_factory=list)
    not_captured: list[str] = Field(default_factory=list)
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


class WordPracticeResult(BaseModel):
    word: str
    result: WordResult
    said_in_dialect: bool = False


class DialectBridge(BaseModel):
    child_word: str
    hindi_word: str


class LearningRecord(BaseModel):
    learner_name: Optional[str] = None
    date: Optional[str] = None
    duration_est: Optional[int] = None
    mode_used: Optional[LearningMode] = None
    mood_start: Optional[LearningMood] = None
    topic: Optional[str] = None
    words_practiced: list[WordPracticeResult] = Field(default_factory=list)
    new_words_clear: Optional[int] = None
    emerging_words: Optional[int] = None
    pronunciation_note: Optional[str] = None
    dialect_bridges: list[DialectBridge] = Field(default_factory=list)
    milestone_signal: Optional[str] = None
    engagement: Optional[str] = None
    flags: Optional[LearningFlag] = "none"
    next_focus: list[str] = Field(default_factory=list)
    friendly_summary: Optional[str] = None


class KioskSession(BaseModel):
    session_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    centre_id: str
    phone: Optional[str] = None
    language: str = "hi"
    gender: str = "unknown"
    learner_name: Optional[str] = None
    lesson_topic: Optional[str] = None
    phase: Literal["complaint", "lesson", "result"] = "complaint"
    status: Literal["active", "partial", "completed"] = "active"
    complaint_number: Optional[str] = None
    finish_session_type: Optional[str] = None
    finish_print_mode: Optional[str] = None
    grievance: Optional[GrievanceRecord] = None
    learning_record: Optional[LearningRecord] = None
    lesson_state: Optional[dict[str, Any]] = None
    transcript: list[KioskTranscriptEntry] = []
    turn_count: int = 0
    deleted_at: Optional[datetime] = None
    started_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    ended_at: Optional[datetime] = None
