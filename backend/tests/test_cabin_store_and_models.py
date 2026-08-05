"""Store fallback behaviour and model-shape guards.

The model tests look trivial but guard a specific hazard: a required field on a
structured-output schema forces the model to fabricate a value. For a medication
dose rendered on a clinical screen, that is a patient-safety bug, not a formatting one.
"""

from __future__ import annotations

from datetime import datetime

import pytest

from app.cabin.models import (
    CabinSession,
    ClinicalPanel,
    DiscussedMedication,
    LiveSuggestions,
    RoleAttribution,
    Utterance,
    UtteranceRole,
)
from app.cabin.store import cabin_session_store
from app.clinical.context import Medication, Specialty


def make_session(session_id: str = "s1", doctor_id: str = "doc-1") -> CabinSession:
    return CabinSession(
        session_id=session_id,
        doctor_id=doctor_id,
        specialty=Specialty.GENERAL_MEDICINE,
        consent_captured_at=datetime.utcnow(),
    )


# ── structured-output schema safety ───────────────────────────────────────


def test_panel_and_suggestion_schemas_have_no_required_fields():
    """Forced tool-choice fills every required field. If any were required the model
    would invent content rather than return an empty section."""
    for schema_cls in (ClinicalPanel, LiveSuggestions, RoleAttribution):
        assert (
            schema_cls().model_json_schema().get("required") is None
        ), schema_cls.__name__


def test_discussed_medication_allows_unknown_dose():
    """'We'll start you on metformin' states no dose. The panel model must be able to
    represent that; clinical.context.Medication cannot, which is why it is not reused.
    """
    med = DiscussedMedication(drug_name="metformin", action="discussed")
    assert med.dose is None and med.frequency is None

    with pytest.raises(Exception):
        Medication(drug_name="metformin")  # required dose/frequency/duration


def test_utterance_defaults_are_unknown_not_guessed():
    utterance = Utterance(utterance_id="u1", seq=0, text="hello")
    assert utterance.role == UtteranceRole.UNKNOWN
    assert utterance.role_confidence == 0.0
    assert utterance.role_source == "llm"
    assert utterance.speaker_id is None  # the diarizer seam


def test_new_session_defaults_are_safe():
    session = CabinSession(
        session_id="s", doctor_id="d", specialty=Specialty.GENERAL_MEDICINE
    )
    assert session.consent_captured_at is None, "consent must never default to granted"
    assert session.roles_verified is False
    assert session.status == "active"
    assert session.audio_key is None


# ── store fallback ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_and_get_round_trip():
    await cabin_session_store.create(make_session())
    loaded = await cabin_session_store.get("s1")
    assert loaded is not None
    assert loaded.doctor_id == "doc-1"


@pytest.mark.asyncio
async def test_get_is_scoped_by_doctor():
    await cabin_session_store.create(make_session())
    assert await cabin_session_store.get("s1", doctor_id="doc-1") is not None
    assert await cabin_session_store.get("s1", doctor_id="doc-2") is None


@pytest.mark.asyncio
async def test_update_persists_utterances_and_panel():
    session = make_session()
    await cabin_session_store.create(session)

    session.utterances = [Utterance(utterance_id="u1", seq=0, text="fever")]
    session.panel = ClinicalPanel()
    session.status = "ended"
    await cabin_session_store.update(session)

    loaded = await cabin_session_store.get("s1")
    assert len(loaded.utterances) == 1
    assert loaded.status == "ended"
    assert loaded.panel is not None


@pytest.mark.asyncio
async def test_update_refreshes_updated_at():
    session = make_session()
    await cabin_session_store.create(session)
    original = session.updated_at
    await cabin_session_store.update(session)
    assert session.updated_at >= original


@pytest.mark.asyncio
async def test_delete_removes_the_session():
    await cabin_session_store.create(make_session())
    await cabin_session_store.delete("s1")
    assert await cabin_session_store.get("s1") is None


@pytest.mark.asyncio
async def test_missing_session_returns_none():
    assert await cabin_session_store.get("never-existed") is None


@pytest.mark.asyncio
async def test_cabin_store_latch_is_independent_of_the_questionnaire_store():
    """A cabin write failure must not stop questionnaire sessions from persisting."""
    from app.clinical import session_store as clinical_store

    import app.cabin.store as cabin_store

    assert cabin_store._mongo_write_failed is True  # set by the autouse fixture
    assert (
        clinical_store._mongo_write_failed is False
    ), "cabin failure leaked into the clinical store"
