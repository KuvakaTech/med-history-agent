"""Tests for kiosk Gemini Live tools."""
from __future__ import annotations

import os

os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-for-pytest-only")

from app.kiosk.gemini_live import (
    GeminiLiveSession,
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


def test_v3_complaint_tool_requires_session_and_print_mode():
    tools = complaint_tools(v3=True)
    decl = tools[0].function_declarations[0]
    assert decl.name == "finish_complaint"
    required = set(decl.parameters.required or [])
    assert required == {"reason", "session_type", "print_mode"}
    assert "application_letter" in (decl.description or "")
    assert "citizen name must be confirmed" in (decl.description or "").lower()


def test_parse_order_tool_before_audio_then_turn_complete():
    """finish_complaint/transcript can precede audio; turn_complete is last."""
    live = GeminiLiveSession.__new__(GeminiLiveSession)
    live._agent_buf = ""
    live._user_buf = ""
    live._user_speaking = False
    live._user_final_emitted = False

    class FakeInline:
        data = b"\x00\x01" * 50

    class FakePart:
        inline_data = FakeInline()

    class FakeModelTurn:
        parts = [FakePart()]

    class FakeFunctionCall:
        name = "finish_complaint"
        args = {"reason": "done", "session_type": "complaint", "print_mode": "application_letter"}
        id = "fc-1"

    class FakeToolCall:
        function_calls = [FakeFunctionCall()]

    class FakeOutputTranscription:
        text = "धन्यवाद। आपका दिन शुभ हो।"
        finished = True

    class FakeServerContent:
        interrupted = False
        interim_input_transcription = None
        input_transcription = None
        output_transcription = FakeOutputTranscription()
        model_turn = FakeModelTurn()
        turn_complete = True

    class FakeMsg:
        session_resumption_update = None
        go_away = None
        tool_call = FakeToolCall()
        server_content = FakeServerContent()

    events = live._parse(FakeMsg())
    kinds = [e.kind for e in events]
    assert kinds[0] == "tool_call"
    assert "agent_transcript_final" in kinds
    assert "agent_audio_chunk" in kinds
    assert kinds[-1] == "turn_complete"
    tool_idx = kinds.index("tool_call")
    audio_idx = kinds.index("agent_audio_chunk")
    turn_idx = kinds.index("turn_complete")
    assert tool_idx < audio_idx < turn_idx


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
