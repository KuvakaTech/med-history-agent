"""HTTP + WebSocket contract tests for the cabin endpoints.

Multi-tenancy and the consent gate are the two properties worth guarding hardest:
one leaks another doctor's clinical record, the other captures a patient's health data
without a lawful basis under the DPDP Act.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from jose import jwt
from starlette.testclient import WebSocketDenialResponse

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
    # The lifespan hook creates indexes on startup; without this it dials the real
    # cluster from the .env and each test pays the server-selection timeout.
    def unavailable():
        raise RuntimeError("MongoDB intentionally unavailable in tests")

    monkeypatch.setattr("app.main.get_db", unavailable)
    with TestClient(app) as test_client:
        yield test_client


def create_session(client: TestClient, doctor: str = "doc-a", consent: bool = True):
    return client.post(
        "/api/v1/cabin/",
        json={"specialty": "general_medicine", "consent": consent},
        headers=auth(doctor),
    )


# ── consent ───────────────────────────────────────────────────────────────


def test_create_requires_consent(client):
    res = create_session(client, consent=False)
    assert res.status_code == 400
    assert "consent" in res.json()["detail"].lower()


def test_create_records_consent_timestamp(client):
    res = create_session(client)
    assert res.status_code == 201
    assert res.json()["consent_captured_at"] is not None
    assert res.json()["status"] == "active"


def test_consent_field_is_required_not_defaulted(client):
    """Consent must be an explicit decision — omitting it is a validation error, not
    an implicit yes."""
    res = client.post(
        "/api/v1/cabin/", json={"specialty": "general_medicine"}, headers=auth("doc-a")
    )
    assert res.status_code == 422


# ── multi-tenancy ─────────────────────────────────────────────────────────


def test_another_doctor_cannot_read_or_delete_a_session(client):
    session_id = create_session(client, "doc-a").json()["session_id"]

    assert (
        client.get(f"/api/v1/cabin/{session_id}", headers=auth("doc-a")).status_code
        == 200
    )
    assert (
        client.get(f"/api/v1/cabin/{session_id}", headers=auth("doc-b")).status_code
        == 404
    )
    assert (
        client.delete(f"/api/v1/cabin/{session_id}", headers=auth("doc-b")).status_code
        == 404
    )
    # Still there after the failed cross-tenant delete.
    assert (
        client.get(f"/api/v1/cabin/{session_id}", headers=auth("doc-a")).status_code
        == 200
    )


def test_unauthenticated_requests_are_rejected(client):
    unauth = client.post(
        "/api/v1/cabin/", json={"specialty": "general_medicine", "consent": True}
    )
    assert unauth.status_code in (401, 403)
    assert client.get("/api/v1/cabin/anything").status_code in (401, 403)


def test_delete_removes_the_session(client):
    session_id = create_session(client).json()["session_id"]
    assert (
        client.delete(f"/api/v1/cabin/{session_id}", headers=auth("doc-a")).status_code
        == 200
    )
    assert (
        client.get(f"/api/v1/cabin/{session_id}", headers=auth("doc-a")).status_code
        == 404
    )


# ── websocket auth ────────────────────────────────────────────────────────


def test_websocket_rejects_a_bad_token(client):
    with pytest.raises(WebSocketDenialResponse) as exc:
        with client.websocket_connect(
            "/api/v1/cabin/any-session/stream?token=nonsense"
        ):
            pass
    assert exc.value.status_code == 401


def test_websocket_rejects_a_session_owned_by_another_doctor(client):
    session_id = create_session(client, "doc-a").json()["session_id"]
    with client.websocket_connect(
        f"/api/v1/cabin/{session_id}/stream?token={token_for('doc-b')}"
    ) as ws:
        message = ws.receive_json()
    assert message["type"] == "error"
    assert message["fatal"] is True


# ── concurrency cap and the cross-worker lease ────────────────────────────


def test_a_doctor_over_the_concurrency_cap_is_refused(client, monkeypatch):
    """The cap is what stops one account holding unlimited ElevenLabs sockets, since
    SlowAPIMiddleware does not cover WebSocket routes."""
    monkeypatch.setattr(settings, "CABIN_MAX_CONCURRENT_SESSIONS_PER_DOCTOR", 0)
    session_id = create_session(client, "doc-a").json()["session_id"]

    with client.websocket_connect(
        f"/api/v1/cabin/{session_id}/stream?token={token_for('doc-a')}"
    ) as ws:
        message = ws.receive_json()

    assert message["code"] == "session_limit"
    assert message["fatal"] is True
    assert message["limit"] == 0


def test_a_second_socket_on_one_session_is_refused(client, monkeypatch):
    """Two live sockets on one session_id open two consults and double-bill them."""
    session_id = create_session(client, "doc-a").json()["session_id"]

    async def already_held(session_id, doctor_id):
        return False

    monkeypatch.setattr("app.api.v1.endpoints.cabin.leases.acquire", already_held)
    with client.websocket_connect(
        f"/api/v1/cabin/{session_id}/stream?token={token_for('doc-a')}"
    ) as ws:
        message = ws.receive_json()

    assert message["code"] == "duplicate_connection"
    assert message["fatal"] is True


def test_ownership_is_checked_before_the_cap(client, monkeypatch):
    """A doctor at the cap requesting someone else's session gets 'not found', not a
    limit message that would confirm the session exists."""
    monkeypatch.setattr(settings, "CABIN_MAX_CONCURRENT_SESSIONS_PER_DOCTOR", 0)
    session_id = create_session(client, "doc-a").json()["session_id"]

    with client.websocket_connect(
        f"/api/v1/cabin/{session_id}/stream?token={token_for('doc-b')}"
    ) as ws:
        message = ws.receive_json()

    assert message["code"] == "session_not_found"


def test_the_lease_is_released_when_the_socket_closes(client, monkeypatch):
    """Released in the endpoint's finally, so it also covers run() raising."""
    session_id = create_session(client, "doc-a").json()["session_id"]
    released: list[str] = []

    async def record_release(session_id):
        released.append(session_id)

    async def boom(self):
        raise RuntimeError("session blew up")

    monkeypatch.setattr("app.api.v1.endpoints.cabin.leases.release", record_release)
    monkeypatch.setattr("app.cabin.live.CabinLiveSession.run", boom)

    with client.websocket_connect(
        f"/api/v1/cabin/{session_id}/stream?token={token_for('doc-a')}"
    ):
        pass

    assert released == [session_id]


def test_openapi_exposes_the_cabin_routes(client):
    paths = client.get("/openapi.json").json()["paths"]
    assert "/api/v1/cabin/" in paths
    assert "/api/v1/cabin/{session_id}" in paths
