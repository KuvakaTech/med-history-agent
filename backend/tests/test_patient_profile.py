"""Profile building: what the doctor asserted vs what prior consultations imply.

The distinction is the point. A derived condition came from an LLM reading a transcript;
presenting it as though the doctor had confirmed it would be a quiet escalation of
certainty, which is exactly what the clinical prompts elsewhere refuse to do.
"""

from __future__ import annotations

from app.clinical.patient import KnownCondition, Patient
from app.clinical.profile import build_profile


def make_patient(**kw) -> Patient:
    return Patient(doctor_id="doc-a", name="Asha", age=54, **kw)


def prior_with_diagnosis(condition: str) -> dict:
    return {
        "session_id": "prev-1",
        "panel": {"diagnoses": [{"condition": condition, "reasoning": "on metformin"}]},
    }


def test_no_patient_yields_an_empty_profile():
    profile = build_profile(None)
    assert profile.is_empty()


def test_a_patient_with_no_history_is_empty():
    """The common case — a first-time patient — and the cheapest gap-detection outcome."""
    assert build_profile(make_patient(), []).is_empty()


def test_doctor_entered_conditions_are_carried_through():
    patient = make_patient(conditions=[KnownCondition(name="Type 2 diabetes")])
    profile = build_profile(patient, [])
    assert [c.name for c in profile.conditions] == ["Type 2 diabetes"]
    assert profile.conditions[0].source == "doctor"
    assert not profile.is_empty()


def test_conditions_are_derived_from_prior_consultations():
    profile = build_profile(make_patient(), [prior_with_diagnosis("Hypertension")])
    assert [c.name for c in profile.conditions] == ["Hypertension"]
    assert profile.conditions[0].source == "derived"
    assert profile.conditions[0].detail == "on metformin"


def test_a_doctor_entry_wins_over_the_same_derived_condition():
    """The doctor asserted it; the system merely inferred it. Never show both, and never
    let the inference displace the assertion."""
    patient = make_patient(
        conditions=[KnownCondition(name="Type 2 Diabetes", detail="well controlled")]
    )
    profile = build_profile(patient, [prior_with_diagnosis("type 2 diabetes")])

    assert len(profile.conditions) == 1
    assert profile.conditions[0].source == "doctor"
    assert profile.conditions[0].detail == "well controlled"


def test_the_same_condition_across_several_prior_sessions_appears_once():
    profile = build_profile(
        make_patient(),
        [prior_with_diagnosis("Asthma"), prior_with_diagnosis("asthma")],
    )
    assert len(profile.conditions) == 1


def test_allergies_and_medications_count_as_a_non_empty_profile():
    """An allergy alone is worth checking a consultation against."""
    assert not build_profile(make_patient(allergies=["penicillin"]), []).is_empty()
    assert not build_profile(
        make_patient(current_medications=["metformin"]), []
    ).is_empty()


def test_a_prior_session_without_a_panel_is_skipped():
    profile = build_profile(make_patient(), [{"session_id": "x"}, {"panel": None}])
    assert profile.is_empty()


def test_a_blank_condition_name_is_ignored():
    profile = build_profile(
        make_patient(), [{"panel": {"diagnoses": [{"condition": "  "}]}}]
    )
    assert profile.conditions == []
