from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field


class Specialty(str, Enum):
    GENERAL_MEDICINE = "general_medicine"
    PSYCHOTHERAPY = "psychotherapy"
    GYNECOLOGY = "gynecology"


class ConsultationStage(str, Enum):
    QUESTIONNAIRE = "questionnaire"
    COMPLETENESS_CHECK = "completeness_check"
    SUMMARY = "summary"
    DIAGNOSIS = "diagnosis"
    PRESCRIPTION = "prescription"
    FINALIZED = "finalized"


class QAEntry(BaseModel):
    question_id: str
    question_text: str
    answer: str
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class ClinicalFlag(BaseModel):
    flag_type: str  # CRITICAL_RED_FLAG | RED_FLAG | IMPORTANT | NOTE
    description: str
    source_question_id: Optional[str] = None
    raised_at: datetime = Field(default_factory=datetime.utcnow)


class DoctorOverride(BaseModel):
    stage: ConsultationStage
    field: str
    original_value: Any
    overridden_value: Any
    reason: Optional[str] = None
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class DifferentialDiagnosis(BaseModel):
    condition: str
    likelihood: str  # High | Medium | Low
    reasoning: str
    icd_code: Optional[str] = None


class DiagnosisResult(BaseModel):
    differential_diagnoses: list[DifferentialDiagnosis] = []
    urgent_concerns: list[str] = []
    suggested_workup: list[str] = []
    physician_note: Optional[str] = None


class Medication(BaseModel):
    drug_name: str
    dose: str
    frequency: str
    duration: str
    instructions: Optional[str] = None
    warnings: Optional[str] = None


class PrescriptionResult(BaseModel):
    pharmacological: list[Medication] = []
    non_pharmacological: list[str] = []
    follow_up: Optional[str] = None
    referrals: list[str] = []
    contraindication_warnings: list[str] = []


class CompletenessReport(BaseModel):
    missing_required: list[str] = []
    missing_recommended: list[str] = []
    ready_to_proceed: bool = True


class ConsultationContext(BaseModel):
    # Validate on attribute assignment too (not just construction) — the doctor-override
    # endpoint does setattr(ctx, field, value) with caller-supplied values, and an invalid
    # value written unvalidated would fail to load on every future read (session bricked).
    model_config = ConfigDict(validate_assignment=True)

    session_id: str
    specialty: Specialty
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    current_stage: ConsultationStage = ConsultationStage.QUESTIONNAIRE
    history_complete: bool = False

    # Patient demographics collected at intake
    patient_name: Optional[str] = None
    patient_age: Optional[int] = None
    patient_gender: Optional[str] = None  # Male | Female | Other
    chief_complaint: Optional[str] = None

    patient_language: Optional[str] = None
    clinical_language: str = "en"

    qa_log: list[QAEntry] = []
    current_question: Optional[str] = None
    covered_areas: list[str] = []

    raw_transcript: str = ""
    translated_transcript: str = ""

    flags: list[ClinicalFlag] = []
    completeness_report: Optional[CompletenessReport] = None
    summary: Optional[Any] = None
    diagnosis: Optional[DiagnosisResult] = None
    prescription: Optional[PrescriptionResult] = None

    overrides: list[DoctorOverride] = []

    # R2 keys for stored audio files
    audio_keys: list[str] = []

    # Patient record reference (set when consultation is linked to a patient)
    patient_id: Optional[str] = None

    # Where the session was created (optional — client may not grant location access)
    latitude: Optional[float] = Field(default=None, ge=-90, le=90)
    longitude: Optional[float] = Field(default=None, ge=-180, le=180)
