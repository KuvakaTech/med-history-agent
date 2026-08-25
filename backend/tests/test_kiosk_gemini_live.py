"""Tests for kiosk Gemini Live tools."""
from __future__ import annotations

import os

os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-for-pytest-only")

from app.kiosk.gemini_live import complaint_tools, build_live_config


def test_complaint_tool_name():
    tools = complaint_tools()
    decl = tools[0].function_declarations
    assert decl[0].name == "finish_complaint"
    assert "reason" in (decl[0].parameters.required or [])


def test_kiosk_live_config_has_tools():
    cfg = build_live_config(
        "jan sunwai",
        language_code="hi-IN",
        voice="Puck",
        tools=complaint_tools(),
        model="gemini-3.1-flash-live-preview",
    )
    assert cfg.tools is not None
