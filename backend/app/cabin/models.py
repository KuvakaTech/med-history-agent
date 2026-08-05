from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field

from app.clinical.context import DifferentialDiagnosis, Specialty


class UtteranceRole(str, Enum):
    DOCTOR = "doctor"
    PATIENT = "patient"
    ATTENDEE = "attendee"
    UNKNOWN = "unknown"


class Utterance(BaseModel):
    utterance_id: str
    seq: int
    text: str
    role: UtteranceRole = UtteranceRole.UNKNOWN
    role_confidence: float = 0.0
    role_source: str = "llm"  # "llm" | "diarizer" — set by postprocess.rediarize
    language: Optional[str] = None
    speaker_id: Optional[str] = None  # ElevenLabs cluster hint — the diarizer seam
    started_at: Optional[float] = None
    ended_at: Optional[float] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)


# ── Role attribution (structured LLM output) ──────────────────


class RoleLabel(BaseModel):
    utterance_id: str
    role: UtteranceRole
    confidence: float = Field(ge=0.0, le=1.0)


class RoleAttribution(BaseModel):
    labels: list[RoleLabel] = []


# ── Live suggestions (left pane) ──────────────────────────────


class SuggestedQuestion(BaseModel):
    question: str
    rationale: str


class SuggestedTest(BaseModel):
    test: str
    rationale: str


class LiveSuggestions(BaseModel):
    questions_to_ask: list[SuggestedQuestion] = []
    differentials: list[DifferentialDiagnosis] = []  # icd_code stays null this phase
    tests_to_consider: list[SuggestedTest] = []
    red_flags: list[str] = []


# ── Structured clinical panel (right pane) ────────────────────


class ReportedSymptom(BaseModel):
    name: str
    detail: Optional[str] = None  # onset/duration/severity in one line
    reported_by: UtteranceRole = UtteranceRole.PATIENT


class OrderedTest(BaseModel):
    name: str
    status: str  # "ordered" | "considered"


class DiscussedMedication(BaseModel):
    drug_name: str
    dose: Optional[str] = None
    frequency: Optional[str] = None
    action: str  # "started" | "stopped" | "continued" | "discussed"
    note: Optional[str] = None


class AskedQuestion(BaseModel):
    text: str  # normalized, not verbatim
    area: Optional[str] = None  # e.g. "onset", "past history"


class ClinicalPanel(BaseModel):
    symptoms: list[ReportedSymptom] = []
    diagnoses: list[DifferentialDiagnosis] = []
    tests: list[OrderedTest] = []
    medications: list[DiscussedMedication] = []
    questions_asked: list[AskedQuestion] = []
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class PanelDelta(BaseModel):
    """What the last stretch of conversation added to the panel.

    The panel is built by merging deltas rather than re-extracting the whole thing each
    pass. Re-extraction meant the model re-emitted every entry every 8 seconds — on a
    20-minute consult that is ~72k output tokens spent restating things that had not
    changed, and it was the single largest line item in the run cost. A delta is
    usually a few entries or empty, and the merge happens in Python where it is
    deterministic and testable.
    """

    new_symptoms: list[ReportedSymptom] = []
    new_diagnoses: list[DifferentialDiagnosis] = []
    new_tests: list[OrderedTest] = []
    new_medications: list[DiscussedMedication] = []
    new_questions_asked: list[AskedQuestion] = []

    def has_clinical_change(self) -> bool:
        """Whether anything worth re-reasoning about arrived. Questions the doctor asked
        are deliberately excluded — they churn constantly and would fire the expensive
        suggestion call on every pass, which is the cost the gate exists to avoid."""
        return bool(
            self.new_symptoms
            or self.new_diagnoses
            or self.new_tests
            or self.new_medications
        )


# ── Persisted session document ────────────────────────────────


class ClinicalWorkflow(str, Enum):
    """Where a finished consultation has got to clinically.

    Deliberately separate from CabinSession.status, which is the *connection* lifecycle
    (active | ended | interrupted). Overloading that would conflate "the socket dropped"
    with "the doctor approved".
    """

    DRAFT = "draft"  # ended; nothing done yet
    CODED = "coded"
    PRESCRIBED = "prescribed"
    APPROVED = "approved"  # doctor signed off — the trigger for everything downstream
    SUBMITTED = "submitted"


class CabinOverride(BaseModel):
    """One doctor correction to a finished record.

    Not clinical.context.DoctorOverride, whose `stage` is typed to the questionnaire-only
    ConsultationStage enum.
    """

    field: str
    original_value: Any = None
    overridden_value: Any = None
    reason: Optional[str] = None
    doctor_id: str
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class SessionCost(BaseModel):
    """LLM spend for one consultation, so the run-cost estimate is confirmed against
    real traffic rather than trusted. usd is 0 for models with no price on file; the
    token counts are exact either way."""

    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    usd: float = 0.0
    inr: float = 0.0


class CabinSession(BaseModel):
    session_id: str
    doctor_id: str
    patient_id: Optional[str] = None
    specialty: Specialty
    patient_name: Optional[str] = None
    status: str = "active"  # active | ended | interrupted
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    ended_at: Optional[datetime] = None

    consent_captured_at: Optional[datetime] = None

    utterances: list[Utterance] = []
    panel: Optional[ClinicalPanel] = None
    suggestions: Optional[LiveSuggestions] = None
    stt_warnings: list[str] = []  # warning codes only, for post-hoc quality review

    audio_key: Optional[str] = None
    roles_verified: bool = False  # flipped by postprocess.rediarize on success

    # Optional with a default so sessions persisted before this field still validate.
    cost: Optional[SessionCost] = None

    # Post-consultation. Same reasoning: defaulted, so older documents keep loading.
    workflow: ClinicalWorkflow = ClinicalWorkflow.DRAFT
    overrides: list[CabinOverride] = []
