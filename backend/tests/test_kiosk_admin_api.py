"""HTTP contract tests for kiosk admin API."""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-for-pytest-only")
os.environ.setdefault("KIOSK_ENABLED", "true")

import asyncio
import pytest
from fastapi.testclient import TestClient
from jose import jwt

from app.core.config import settings
from app.kiosk.centre_store import centre_store
from app.kiosk.models import GrievanceRecord, KioskCentre, KioskSession
from app.kiosk.session_store import kiosk_session_store
from app.main import app


def _token(
    user_id: str = "user-1",
    role: str = "centre_admin",
    centre_id: str = "c-test",
) -> str:
    now = datetime.now(timezone.utc)
    return jwt.encode(
        {
            "sub": user_id,
            "email": f"{user_id}@test.local",
            "name": user_id,
            "role": role,
            "centre_id": centre_id,
            "iat": now,
            "exp": now + timedelta(minutes=15),
        },
        settings.JWT_SECRET_KEY,
        algorithm=settings.JWT_ALGORITHM,
    )


def _centre_admin_headers(centre_id: str = "c-test") -> dict:
    return {"Authorization": f"Bearer {_token(centre_id=centre_id)}"}


def _super_headers() -> dict:
    return {"Authorization": f"Bearer {_token(role='super_admin', centre_id=None)}"}


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr("app.main.get_db", lambda: (_ for _ in ()).throw(RuntimeError("no db")))
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


@pytest.fixture
def centre():
    c = KioskCentre(
        centre_id="c-test",
        slug="test-kiosk",
        name="Test Kiosk",
        prompt_file="jan_sunwai_system.txt",
        complaint_prefix="JS-VNS",
    )
    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(centre_store.create(c))
    finally:
        loop.close()
    return c


@pytest.fixture
def other_centre():
    c = KioskCentre(
        centre_id="c-other",
        slug="other-kiosk",
        name="Other Kiosk",
    )
    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(centre_store.create(c))
    finally:
        loop.close()
    return c


def _create_session(centre_id: str, session_id: str, complaint: str | None = None):
    session = KioskSession(
        session_id=session_id,
        centre_id=centre_id,
        phone="9876543210",
        language="hi",
        status="completed",
        complaint_number=complaint,
        grievance=GrievanceRecord(
            full_name="Ram Kumar",
            confirmed_summary="Water issue",
            category="water",
        ),
    )
    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(kiosk_session_store.create(session))
    finally:
        loop.close()
    return session


def test_super_admin_requires_centre_id_for_stats(client, centre):
    r = client.get("/api/v2/kiosk-admin/stats", headers=_super_headers())
    assert r.status_code == 400


def test_centre_admin_stats_scoped(client, centre):
    _create_session(centre.centre_id, "sess-1", "JS-VNS-20250825-00001")
    r = client.get("/api/v2/kiosk-admin/stats", headers=_centre_admin_headers(centre.centre_id))
    assert r.status_code == 200
    assert r.json()["all_time"]["total"] >= 1


def test_centre_admin_cannot_see_other_centre_sessions(client, centre, other_centre):
    _create_session(other_centre.centre_id, "sess-other", "JS-VNS-20250825-00002")
    r = client.get(
        "/api/v2/kiosk-admin/sessions",
        headers=_centre_admin_headers(centre.centre_id),
    )
    assert r.status_code == 200
    ids = [s["session_id"] for s in r.json()["sessions"]]
    assert "sess-other" not in ids


def test_super_admin_lists_with_centre_id(client, centre, other_centre):
    _create_session(centre.centre_id, "sess-a", "JS-VNS-20250825-00003")
    _create_session(other_centre.centre_id, "sess-b", "NN-VNS-20250825-00001")
    r = client.get(
        f"/api/v2/kiosk-admin/sessions?centre_id={centre.centre_id}",
        headers=_super_headers(),
    )
    assert r.status_code == 200
    ids = [s["session_id"] for s in r.json()["sessions"]]
    assert "sess-a" in ids
    assert "sess-b" not in ids


def test_super_admin_global_session_detail(client, centre):
    _create_session(centre.centre_id, "sess-detail", "JS-VNS-20250825-00004")
    r = client.get(
        "/api/v2/kiosk-admin/sessions/sess-detail",
        headers=_super_headers(),
    )
    assert r.status_code == 200
    assert r.json()["session_id"] == "sess-detail"
    assert r.json().get("transcript") is not None


def test_complaint_number_search(client, centre):
    _create_session(centre.centre_id, "sess-search", "JS-VNS-20250825-00099")
    r = client.get(
        f"/api/v2/kiosk-admin/sessions?complaint=JS-VNS-20250825-00099",
        headers=_centre_admin_headers(centre.centre_id),
    )
    assert r.status_code == 200
    assert r.json()["count"] == 1


def test_list_centres_super_admin_only(client, centre):
    r = client.get("/api/v2/kiosk-admin/centres", headers=_centre_admin_headers())
    assert r.status_code == 403
    r2 = client.get("/api/v2/kiosk-admin/centres", headers=_super_headers())
    assert r2.status_code == 200
    assert len(r2.json()["centres"]) >= 1
