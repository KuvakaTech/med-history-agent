"""HTTP contract tests for the ticketing v2 endpoints.

Tests the public patient-facing API (no auth) and admin API (JWT).
MongoDB is never dialled — all stores run in-memory.
LLM/TTS/Deepgram are never called — voice_session is not exercised here.

Covers:
  - POST /api/v2/t/{slug}/session — create session, phone required, ticket_number returned
  - GET  /api/v2/t/{slug}/session/{id}/result — result, deleted sessions hidden from patient
  - POST /api/v2/t/{slug}/session/{id}/discard — soft delete
  - GET  /api/v2/admin/stats — hospital stats
  - GET  /api/v2/admin/sessions — list with filters
  - GET  /api/v2/admin/sessions/{id} — detail
  - GET  /api/v2/admin/categories — list
  - POST /api/v2/admin/categories — create
  - PATCH /api/v2/admin/categories/{id} — toggle
  - POST /api/v2/admin/users — create admin account (super_admin only)
  - Hospital scoping: hospital_admin cannot read another hospital's data
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-for-pytest-only")

import pytest
from fastapi.testclient import TestClient
from jose import jwt

from app.core.config import settings
from app.main import app


# ── token helpers ─────────────────────────────────────────────

def _token(
    user_id: str = "user-1",
    role: str = "hospital_admin",
    hospital_id: str = "h-test",
) -> str:
    now = datetime.now(timezone.utc)
    return jwt.encode(
        {
            "sub": user_id,
            "email": f"{user_id}@test.local",
            "name": user_id,
            "role": role,
            "hospital_id": hospital_id,
            "iat": now,
            "exp": now + timedelta(minutes=15),
        },
        settings.JWT_SECRET_KEY,
        algorithm=settings.JWT_ALGORITHM,
    )


def _admin_headers(hospital_id: str = "h-test") -> dict:
    return {"Authorization": f"Bearer {_token(hospital_id=hospital_id)}"}


def _super_headers() -> dict:
    return {"Authorization": f"Bearer {_token(role='super_admin', hospital_id=None)}"}


# ── fixtures ──────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def isolate_all_stores(monkeypatch):
    """Force every ticketing store into in-memory mode and clear state between tests."""
    import app.ticketing.patient_store as ps
    import app.ticketing.session_store as ss
    import app.ticketing.hospital_store as hs

    def unavailable():
        raise RuntimeError("MongoDB intentionally unavailable in tests")

    for mod in (ps, ss, hs):
        mongo_write = "_mongo_write_failed"
        if hasattr(mod, mongo_write):
            monkeypatch.setattr(mod, mongo_write, True)

    monkeypatch.setattr(ps, "_col", unavailable)
    monkeypatch.setattr(ss, "_col", unavailable)
    monkeypatch.setattr(ss, "_counters_col", unavailable)
    monkeypatch.setattr(hs, "_hospitals_col", unavailable)
    monkeypatch.setattr(hs, "_categories_col", unavailable)

    ps._mem.clear()
    ps._phone_index.clear()
    ss._mem.clear()
    ss._mem_by_ticket.clear()
    ss._local_counter = 0
    hs._mem_hospitals.clear()
    hs._mem_categories.clear()

    yield

    ps._mem.clear(); ps._phone_index.clear()
    ss._mem.clear(); ss._mem_by_ticket.clear(); ss._local_counter = 0
    hs._mem_hospitals.clear(); hs._mem_categories.clear()


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr("app.main.get_db", lambda: (_ for _ in ()).throw(RuntimeError("no db")))
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


@pytest.fixture
def hospital(client):
    """Create a hospital in memory and return its slug + hospital_id."""
    from app.ticketing.hospital_store import hospital_store
    from app.ticketing.models import Hospital
    import asyncio
    h = Hospital(slug="test-hosp", name="Test Hospital")
    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(hospital_store.create(h))
    finally:
        loop.close()
    return h


# ── POST /api/v2/t/{slug}/session ────────────────────────────

def test_start_session_creates_session(client, hospital):
    res = client.post(
        f"/api/v2/t/{hospital.slug}/session",
        json={"phone": "9876543210", "language": "hi", "gender": "female"},
    )
    assert res.status_code == 201
    data = res.json()
    assert "session_id" in data
    assert data["ticket_number"] is not None
    assert data["ticket_number"].startswith("TKT-")
    assert data["language"] == "hi"
    assert data["phase"] == "triage"


def test_start_session_phone_required(client, hospital):
    res = client.post(
        f"/api/v2/t/{hospital.slug}/session",
        json={"phone": "", "language": "hi", "gender": "male"},
    )
    assert res.status_code == 422


def test_start_session_unknown_hospital_returns_404(client):
    res = client.post(
        "/api/v2/t/does-not-exist/session",
        json={"phone": "9000000001"},
    )
    assert res.status_code == 404


def test_start_session_same_phone_reuses_patient(client, hospital):
    r1 = client.post(f"/api/v2/t/{hospital.slug}/session", json={"phone": "9111111111"})
    r2 = client.post(f"/api/v2/t/{hospital.slug}/session", json={"phone": "9111111111"})
    assert r1.status_code == 201
    assert r2.status_code == 201
    assert r1.json()["patient_id"] == r2.json()["patient_id"]


def test_start_session_different_phones_different_patients(client, hospital):
    r1 = client.post(f"/api/v2/t/{hospital.slug}/session", json={"phone": "9222222221"})
    r2 = client.post(f"/api/v2/t/{hospital.slug}/session", json={"phone": "9222222222"})
    assert r1.json()["patient_id"] != r2.json()["patient_id"]


def test_start_session_default_language_from_hospital(client, hospital):
    """When language is not provided, should default to hospital's default_language (hi)."""
    res = client.post(
        f"/api/v2/t/{hospital.slug}/session",
        json={"phone": "9333333333"},
    )
    assert res.status_code == 201
    assert res.json()["language"] == "hi"


def test_ticket_numbers_increment_across_sessions(client, hospital):
    r1 = client.post(f"/api/v2/t/{hospital.slug}/session", json={"phone": "9444444441"})
    r2 = client.post(f"/api/v2/t/{hospital.slug}/session", json={"phone": "9444444442"})
    n1 = int(r1.json()["ticket_number"].split("-")[1])
    n2 = int(r2.json()["ticket_number"].split("-")[1])
    assert n2 == n1 + 1


# ── GET /api/v2/t/{slug}/session/{id}/result ─────────────────

def test_get_result_returns_session(client, hospital):
    r = client.post(f"/api/v2/t/{hospital.slug}/session", json={"phone": "9555555551"})
    sid = r.json()["session_id"]
    slug = hospital.slug
    res = client.get(f"/api/v2/t/{slug}/session/{sid}/result")
    assert res.status_code == 200
    data = res.json()
    assert data["session_id"] == sid
    assert data["ticket_number"] is not None
    assert data["hospital_name"] == "Test Hospital"
    assert data["patient"] is not None
    assert data["patient"]["phone"] == "9555555551"


def test_get_result_unknown_session_returns_404(client, hospital):
    res = client.get(f"/api/v2/t/{hospital.slug}/session/nonexistent/result")
    assert res.status_code == 404


def test_get_result_discarded_session_hidden_from_patient(client, hospital):
    r = client.post(f"/api/v2/t/{hospital.slug}/session", json={"phone": "9666666661"})
    sid = r.json()["session_id"]
    client.post(f"/api/v2/t/{hospital.slug}/session/{sid}/discard")
    res = client.get(f"/api/v2/t/{hospital.slug}/session/{sid}/result")
    assert res.status_code == 404, "discarded session should be hidden from patient"


# ── POST /api/v2/t/{slug}/session/{id}/discard ───────────────

def test_discard_soft_deletes_session(client, hospital):
    r = client.post(f"/api/v2/t/{hospital.slug}/session", json={"phone": "9777777771"})
    sid = r.json()["session_id"]
    res = client.post(f"/api/v2/t/{hospital.slug}/session/{sid}/discard")
    assert res.status_code == 200
    assert res.json()["discarded"] == sid


def test_discard_unknown_session_returns_404(client, hospital):
    res = client.post(f"/api/v2/t/{hospital.slug}/session/bad-id/discard")
    assert res.status_code == 404


# ── GET /api/v2/admin/stats ───────────────────────────────────

def test_admin_stats_returns_today_counts(client, hospital):
    # Create two sessions for this hospital
    client.post(f"/api/v2/t/{hospital.slug}/session", json={"phone": "9888888881"})
    client.post(f"/api/v2/t/{hospital.slug}/session", json={"phone": "9888888882"})

    res = client.get(
        f"/api/v2/admin/stats",
        headers=_admin_headers(hospital.hospital_id),
    )
    assert res.status_code == 200
    data = res.json()
    assert "today" in data
    assert "all_time" in data
    assert data["today"]["total"] >= 2
    assert data["all_time"]["total"] >= 2


def test_admin_stats_requires_auth(client):
    # No token → 401 Unauthorized (not 403, which requires a valid token with wrong role)
    res = client.get("/api/v2/admin/stats")
    assert res.status_code == 401


def test_admin_stats_doctor_role_forbidden(client, hospital):
    doctor_token = _token(role="doctor", hospital_id=hospital.hospital_id)
    res = client.get(
        "/api/v2/admin/stats",
        headers={"Authorization": f"Bearer {doctor_token}"},
    )
    assert res.status_code == 403


# ── GET /api/v2/admin/sessions ────────────────────────────────

def test_admin_list_sessions_returns_sessions(client, hospital):
    client.post(f"/api/v2/t/{hospital.slug}/session", json={"phone": "9999999991"})
    res = client.get("/api/v2/admin/sessions", headers=_admin_headers(hospital.hospital_id))
    assert res.status_code == 200
    data = res.json()
    assert "sessions" in data
    assert data["count"] >= 1


def test_admin_list_sessions_includes_ticket_number(client, hospital):
    client.post(f"/api/v2/t/{hospital.slug}/session", json={"phone": "9999999992"})
    res = client.get("/api/v2/admin/sessions", headers=_admin_headers(hospital.hospital_id))
    sessions = res.json()["sessions"]
    assert all("ticket_number" in s for s in sessions)
    assert all(s["ticket_number"].startswith("TKT-") for s in sessions if s["ticket_number"])


def test_admin_list_sessions_scoped_to_hospital(client, hospital):
    """hospital_admin for h-other cannot see sessions from test-hosp."""
    client.post(f"/api/v2/t/{hospital.slug}/session", json={"phone": "9000000010"})
    res = client.get(
        "/api/v2/admin/sessions",
        headers=_admin_headers("h-completely-other"),
    )
    # Returns 200 but should have 0 sessions for a different hospital
    sessions = res.json()["sessions"]
    assert len(sessions) == 0


def test_admin_list_sessions_filter_by_status(client, hospital):
    client.post(f"/api/v2/t/{hospital.slug}/session", json={"phone": "9000000011"})
    res = client.get(
        "/api/v2/admin/sessions?status=active",
        headers=_admin_headers(hospital.hospital_id),
    )
    assert res.status_code == 200
    for s in res.json()["sessions"]:
        assert s["status"] == "active"


def test_admin_list_sessions_search_by_ticket(client, hospital):
    r = client.post(f"/api/v2/t/{hospital.slug}/session", json={"phone": "9000000012"})
    ticket = r.json()["ticket_number"]
    res = client.get(
        f"/api/v2/admin/sessions?ticket={ticket}",
        headers=_admin_headers(hospital.hospital_id),
    )
    assert res.status_code == 200
    sessions = res.json()["sessions"]
    assert len(sessions) == 1
    assert sessions[0]["ticket_number"] == ticket


# ── GET /api/v2/admin/sessions/{id} ──────────────────────────

def test_admin_get_session_detail_includes_patient(client, hospital):
    r = client.post(f"/api/v2/t/{hospital.slug}/session", json={"phone": "9100000001"})
    sid = r.json()["session_id"]
    res = client.get(
        f"/api/v2/admin/sessions/{sid}",
        headers=_admin_headers(hospital.hospital_id),
    )
    assert res.status_code == 200
    data = res.json()
    assert data["patient"] is not None
    assert data["patient"]["phone"] == "9100000001"
    assert "ticket_number" in data
    assert "started_at_ist" in data


def test_admin_get_session_detail_includes_discarded(client, hospital):
    """Admin can see discarded sessions."""
    r = client.post(f"/api/v2/t/{hospital.slug}/session", json={"phone": "9100000002"})
    sid = r.json()["session_id"]
    client.post(f"/api/v2/t/{hospital.slug}/session/{sid}/discard")
    res = client.get(
        f"/api/v2/admin/sessions/{sid}",
        headers=_admin_headers(hospital.hospital_id),
    )
    assert res.status_code == 200
    assert res.json()["deleted_at"] is not None


def test_admin_get_session_wrong_hospital_returns_404(client, hospital):
    r = client.post(f"/api/v2/t/{hospital.slug}/session", json={"phone": "9100000003"})
    sid = r.json()["session_id"]
    res = client.get(
        f"/api/v2/admin/sessions/{sid}",
        headers=_admin_headers("completely-other-hospital"),
    )
    assert res.status_code == 404


# ── GET /api/v2/admin/categories ─────────────────────────────

def test_admin_list_categories(client, hospital):
    res = client.get(
        "/api/v2/admin/categories",
        headers=_admin_headers(hospital.hospital_id),
    )
    assert res.status_code == 200
    cats = res.json()["categories"]
    assert len(cats) > 0
    keys = {c["key"] for c in cats}
    assert "general_medicine" in keys


def test_admin_create_category(client, hospital):
    res = client.post(
        "/api/v2/admin/categories",
        json={"key": "nephrology", "label": "Nephrology"},
        headers=_admin_headers(hospital.hospital_id),
    )
    assert res.status_code == 201
    assert res.json()["key"] == "nephrology"
    assert res.json()["label"] == "Nephrology"
    assert res.json()["active"] is True


def test_admin_toggle_category_inactive(client, hospital):
    cats = client.get(
        "/api/v2/admin/categories",
        headers=_admin_headers(hospital.hospital_id),
    ).json()["categories"]
    cat = cats[0]
    cat_id = cat["category_id"]

    res = client.patch(
        f"/api/v2/admin/categories/{cat_id}",
        json={"active": False},
        headers=_admin_headers(hospital.hospital_id),
    )
    assert res.status_code == 200
    assert res.json()["active"] is False


def test_admin_update_category_label(client, hospital):
    cats = client.get(
        "/api/v2/admin/categories",
        headers=_admin_headers(hospital.hospital_id),
    ).json()["categories"]
    cat_id = cats[0]["category_id"]
    res = client.patch(
        f"/api/v2/admin/categories/{cat_id}",
        json={"label": "New Label"},
        headers=_admin_headers(hospital.hospital_id),
    )
    assert res.status_code == 200
    assert res.json()["label"] == "New Label"


def test_admin_category_wrong_hospital_returns_404(client, hospital):
    cats = client.get(
        "/api/v2/admin/categories",
        headers=_admin_headers(hospital.hospital_id),
    ).json()["categories"]
    cat_id = cats[0]["category_id"]
    res = client.patch(
        f"/api/v2/admin/categories/{cat_id}",
        json={"active": False},
        headers=_admin_headers("wrong-hospital"),
    )
    assert res.status_code == 404


# ── POST /api/v2/admin/users ──────────────────────────────────

def test_super_admin_can_create_hospital_admin(client, hospital):
    from unittest.mock import AsyncMock, patch

    fake_user = {
        "_id": "fake-id",
        "email": "admin@example.com",
        "name": "Admin User",
        "role": "hospital_admin",
        "hospital_id": hospital.hospital_id,
    }

    with patch("app.api.v2.endpoints.ticketing_admin.user_store.create_admin", new=AsyncMock(return_value=fake_user)), \
         patch("app.api.v2.endpoints.ticketing_admin.hospital_store.get", new=AsyncMock(return_value=hospital)):
        res = client.post(
            "/api/v2/admin/users",
            json={
                "email": "admin@example.com",
                "name": "Admin User",
                "password": "securepass",
                "role": "hospital_admin",
                "hospital_id": hospital.hospital_id,
            },
            headers=_super_headers(),
        )
    assert res.status_code == 201
    data = res.json()
    assert data["role"] == "hospital_admin"
    assert data["email"] == "admin@example.com"


def test_hospital_admin_cannot_create_users(client, hospital):
    res = client.post(
        "/api/v2/admin/users",
        json={
            "email": "someone@test.local",
            "name": "Someone",
            "password": "password123",
            "role": "hospital_admin",
            "hospital_id": hospital.hospital_id,
        },
        headers=_admin_headers(hospital.hospital_id),
    )
    assert res.status_code == 403


def test_create_hospital_admin_without_hospital_id_fails(client, hospital):
    res = client.post(
        "/api/v2/admin/users",
        json={
            "email": "nohospital@test.local",
            "name": "No Hospital",
            "password": "password123",
            "role": "hospital_admin",
            # hospital_id intentionally missing
        },
        headers=_super_headers(),
    )
    assert res.status_code == 422


# ── GET /api/v2/admin/hospitals (super_admin) ────────────────

def test_super_admin_can_list_hospitals(client, hospital):
    res = client.get("/api/v2/admin/hospitals", headers=_super_headers())
    assert res.status_code == 200
    hospitals = res.json()["hospitals"]
    assert any(h["slug"] == hospital.slug for h in hospitals)


def test_hospital_admin_cannot_list_hospitals(client, hospital):
    res = client.get(
        "/api/v2/admin/hospitals",
        headers=_admin_headers(hospital.hospital_id),
    )
    assert res.status_code == 403


def test_super_admin_can_create_hospital(client):
    res = client.post(
        "/api/v2/admin/hospitals",
        json={"slug": "new-hospital", "name": "New Hospital", "default_language": "hi"},
        headers=_super_headers(),
    )
    assert res.status_code == 201
    assert res.json()["slug"] == "new-hospital"


def test_duplicate_hospital_slug_returns_409(client, hospital):
    res = client.post(
        "/api/v2/admin/hospitals",
        json={"slug": hospital.slug, "name": "Duplicate"},
        headers=_super_headers(),
    )
    assert res.status_code == 409
