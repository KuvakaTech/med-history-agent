"""The post-consultation read surface: list, full record, and the override audit trail.

Everything in Phase 2 — coding, prescription, claims — reads through these, so tenancy
scoping is guarded as hard here as it is on the live socket.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from jose import jwt

from app.cabin import store as cabin_store
from app.cabin.models import CabinSession, ClinicalPanel, ReportedSymptom
from app.clinical.context import Specialty
from app.core.config import settings
from app.main import app


def token_for(doctor_id: str) -> str:
    now = datetime.now(timezone.utc)
    return jwt.encode(
        {
            "sub": doctor_id,
            "email": f"{doctor_id}@test.local",
            "name": doctor_id,
            "iat": now,
            "exp": now + timedelta(minutes=15),
        },
        settings.JWT_SECRET_KEY,
        algorithm=settings.JWT_ALGORITHM,
    )


def auth(doctor_id: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token_for(doctor_id)}"}


@pytest.fixture
def client(monkeypatch):
    def unavailable():
        raise RuntimeError("MongoDB intentionally unavailable in tests")

    monkeypatch.setattr("app.main.get_db", unavailable)
    with TestClient(app) as c:
        yield c


async def seed(
    doctor_id: str, patient_id: str | None = None, status: str = "ended"
) -> CabinSession:
    """Writes straight through the store, which is on its in-memory fallback here.

    Defaults to an ended session: corrections are only accepted once a consultation is
    over, because a live one is overwritten by the flush loop every 15s.
    """
    session = CabinSession(
        session_id=f"sess-{doctor_id}-{patient_id or 'none'}",
        doctor_id=doctor_id,
        patient_id=patient_id,
        specialty=Specialty.GENERAL_MEDICINE,
        status=status,
        consent_captured_at=datetime.utcnow(),
        panel=ClinicalPanel(symptoms=[ReportedSymptom(name="fever")]),
    )
    await cabin_store.cabin_session_store.create(session)
    return session


# ── list ──────────────────────────────────────────────────────────────────


async def test_list_returns_only_this_doctors_sessions(client):
    await seed("doc-a")
    await seed("doc-b")

    rows = client.get("/api/v1/cabin/", headers=auth("doc-a")).json()["sessions"]
    assert [r["doctor_id"] for r in rows] == ["doc-a"]


async def test_list_filters_by_patient(client):
    await seed("doc-a", patient_id="pat-1")
    await seed("doc-a", patient_id="pat-2")

    rows = client.get("/api/v1/cabin/?patient_id=pat-1", headers=auth("doc-a")).json()[
        "sessions"
    ]
    assert [r["patient_id"] for r in rows] == ["pat-1"]


async def test_list_omits_the_transcript(client):
    """A list view must not ship a 90-minute transcript per row."""
    await seed("doc-a")
    rows = client.get("/api/v1/cabin/", headers=auth("doc-a")).json()["sessions"]
    assert "utterances" not in rows[0]
    assert "suggestions" not in rows[0]
    assert rows[0]["panel"] is not None, "the panel is what makes a list row useful"


# ── full record ───────────────────────────────────────────────────────────


async def test_record_returns_the_clinical_content(client):
    session = await seed("doc-a")
    body = client.get(
        f"/api/v1/cabin/{session.session_id}/record", headers=auth("doc-a")
    ).json()

    assert body["panel"]["symptoms"][0]["name"] == "fever"
    assert body["workflow"] == "draft"
    assert body["specialty"] == "general_medicine"


async def test_record_is_scoped_to_the_owning_doctor(client):
    session = await seed("doc-a")
    resp = client.get(
        f"/api/v1/cabin/{session.session_id}/record", headers=auth("doc-b")
    )
    assert resp.status_code == 404, "leaked another doctor's clinical record"


async def test_record_does_not_expose_the_audio_key(client):
    session = await seed("doc-a")
    body = client.get(
        f"/api/v1/cabin/{session.session_id}/record", headers=auth("doc-a")
    ).json()
    assert "audio_key" not in body


# ── override ──────────────────────────────────────────────────────────────


async def test_override_records_an_audit_entry(client):
    session = await seed("doc-a")
    resp = client.post(
        f"/api/v1/cabin/{session.session_id}/override",
        headers=auth("doc-a"),
        json={"field": "patient_name", "value": "Corrected Name", "reason": "misheard"},
    )
    assert resp.status_code == 200

    body = client.get(
        f"/api/v1/cabin/{session.session_id}/record", headers=auth("doc-a")
    ).json()
    assert body["patient_name"] == "Corrected Name"
    assert len(body["overrides"]) == 1
    entry = body["overrides"][0]
    assert entry["field"] == "patient_name"
    assert entry["reason"] == "misheard"
    assert entry["doctor_id"] == "doc-a"


async def test_an_invalid_override_is_rejected_and_changes_nothing(client):
    """The property validate_assignment gives ConsultationContext, bought here without
    paying for revalidation on every 15s flush."""
    session = await seed("doc-a")
    resp = client.post(
        f"/api/v1/cabin/{session.session_id}/override",
        headers=auth("doc-a"),
        json={"field": "status", "value": {"not": "a string"}},
    )
    assert resp.status_code == 422

    body = client.get(
        f"/api/v1/cabin/{session.session_id}/record", headers=auth("doc-a")
    ).json()
    assert body["status"] == "ended", "a rejected override still mutated the session"
    assert body["overrides"] == []


async def test_protected_fields_cannot_be_overridden(client):
    """Rewriting doctor_id would move the record to another tenant; rewriting overrides
    would erase the audit trail."""
    session = await seed("doc-a")
    for field in ("doctor_id", "session_id", "overrides", "consent_captured_at"):
        resp = client.post(
            f"/api/v1/cabin/{session.session_id}/override",
            headers=auth("doc-a"),
            json={"field": field, "value": "x"},
        )
        assert resp.status_code == 422, f"{field} was overridable"


async def test_override_on_another_doctors_session_is_404(client):
    session = await seed("doc-a")
    resp = client.post(
        f"/api/v1/cabin/{session.session_id}/override",
        headers=auth("doc-b"),
        json={"field": "patient_name", "value": "x"},
    )
    assert resp.status_code == 404


async def test_unknown_field_is_rejected(client):
    session = await seed("doc-a")
    resp = client.post(
        f"/api/v1/cabin/{session.session_id}/override",
        headers=auth("doc-a"),
        json={"field": "not_a_field", "value": "x"},
    )
    assert resp.status_code == 422


async def test_override_is_refused_while_the_consultation_is_live(client):
    """_flush overwrites the stored panel every 15s, so a correction applied now would
    vanish without trace. Refuse it rather than accept it and lose it."""
    session = await seed("doc-a", status="active")
    resp = client.post(
        f"/api/v1/cabin/{session.session_id}/override",
        headers=auth("doc-a"),
        json={"field": "patient_name", "value": "x"},
    )
    assert resp.status_code == 409


async def test_record_never_exposes_cost(client):
    """Per-consult LLM spend is unit economics, not clinical data."""
    session = await seed("doc-a")
    body = client.get(
        f"/api/v1/cabin/{session.session_id}/record", headers=auth("doc-a")
    ).json()
    assert "cost" not in body

    rows = client.get("/api/v1/cabin/", headers=auth("doc-a")).json()["sessions"]
    assert "cost" not in rows[0]
