"""Tests for kiosk Gemini Live tools."""
from __future__ import annotations

import os

os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-for-pytest-only")

from app.kiosk.gemini_live import (
    complaint_tools,
    lesson_tools,
    build_live_config,
    dedupe_concatenated_repeats,
    collapse_repeated_suffix,
    sanitize_agent_transcript,
)


def test_lesson_tool_name():
    tools = lesson_tools()
    decl = tools[0].function_declarations
    names = [d.name for d in decl]
    assert "show_word_card" in names
    assert "finish_lesson" in names


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


def test_sanitize_strips_tool_leak():
    raw = 'call:finish_complaint{"reason":"done"}धन्यवाद।'
    assert "call:finish" not in sanitize_agent_transcript(raw)
    assert "धन्यवाद" in sanitize_agent_transcript(raw)


def test_dedupe_concatenated_repeats():
    unit = "कोई बात नहीं जी। धन्यवाद।"
    repeated = unit * 5
    assert dedupe_concatenated_repeats(repeated) == unit


def test_collapse_repeated_suffix():
    prefix = "आपकी समस्या दर्ज कर ली गई है। "
    unit = "कोई बात नहीं जी। जन सुनवाई में आने के लिए धन्यवाद। आपका दिन शुभ हो।"
    text = prefix + unit * 4
    collapsed = sanitize_agent_transcript(text)
    assert collapsed == prefix + unit
    assert unit * 2 not in collapsed
