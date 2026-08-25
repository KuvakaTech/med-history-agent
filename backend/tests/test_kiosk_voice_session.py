"""Tests for kiosk voice session finish_complaint handling."""
from __future__ import annotations

import os
from unittest.mock import AsyncMock, MagicMock

os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-for-pytest-only")

import pytest

from app.kiosk.gemini_live import LiveEvent
from app.kiosk.models import KioskCentre, KioskSession
from app.kiosk.voice_session import KioskVoiceSession


@pytest.mark.asyncio
async def test_finish_complaint_sets_phase_done():
    session = KioskSession(centre_id="c1", phone="9999999999", language="hi")
    centre = KioskCentre(slug="varanasi-jan-sunwai", name="Jan Sunwai")
    ws = MagicMock()
    ws.send_json = AsyncMock()
    voice = KioskVoiceSession(session=session, ws=ws, centre=centre)
    voice._live = MagicMock()
    voice._live.send_tool_response = AsyncMock()

    event = LiveEvent(
        kind="tool_call",
        tool_name="finish_complaint",
        tool_args={"reason": "complete"},
        tool_call_id="call-1",
    )
    await voice._handle_live_event(event)

    assert voice._phase_done.is_set()
    voice._live.send_tool_response.assert_awaited_once()
