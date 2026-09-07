"""Tests for kiosk public API — learning centre validation."""
from __future__ import annotations

import os
from unittest.mock import AsyncMock, patch

os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-for-pytest-only")

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.kiosk.models import KioskCentre


@pytest.fixture
def guddi_centre():
    return KioskCentre(
        centre_id="guddi-centre-1",
        slug="barwani-guddi",
        name="Guddi Learning",
        centre_kind="learning",
        prompt_file="guddi_learning_system.txt",
    )


@pytest.mark.asyncio
async def test_learning_start_requires_topic(guddi_centre):
    with patch(
        "app.api.v2.endpoints.kiosk.centre_store.get_by_slug",
        new_callable=AsyncMock,
        return_value=guddi_centre,
    ):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            res = await client.post(
                "/api/v2/kiosk/barwani-guddi/session",
                json={"learner_name": "Kavita"},
            )
    assert res.status_code == 422


@pytest.mark.asyncio
async def test_learning_start_success(guddi_centre):
    with patch(
        "app.api.v2.endpoints.kiosk.centre_store.get_by_slug",
        new_callable=AsyncMock,
        return_value=guddi_centre,
    ):
        with patch(
            "app.api.v2.endpoints.kiosk.kiosk_session_store.create",
            new_callable=AsyncMock,
        ) as mock_create:
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                res = await client.post(
                    "/api/v2/kiosk/barwani-guddi/session",
                    json={"learner_name": "Kavita", "lesson_topic": "Ghar"},
                )
    assert res.status_code == 201
    data = res.json()
    assert data["lesson_topic"] == "Ghar"
    assert data["learner_name"] == "Kavita"
    assert data["phase"] == "lesson"
    mock_create.assert_awaited_once()


@pytest.mark.asyncio
async def test_get_centre_returns_kind(guddi_centre):
    with patch(
        "app.api.v2.endpoints.kiosk.centre_store.get_by_slug",
        new_callable=AsyncMock,
        return_value=guddi_centre,
    ):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            res = await client.get("/api/v2/kiosk/barwani-guddi")
    assert res.status_code == 200
    assert res.json()["centre_kind"] == "learning"
