from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


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
