"""Offline tests for the Gemini Live wrapper (no network)."""
from __future__ import annotations

import os
from types import SimpleNamespace

os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-for-pytest-only")

from app.ticketing.gemini_live import (
    GeminiLiveSession,
    bcp47_language,
    build_live_config,
    consultation_tools,
    dedupe_concatenated_repeats,
    is_native_audio_model,
    merge_transcript_chunk,
    sanitize_agent_transcript,
    triage_tools,
)
from app.ticketing.models import TicketCategory
from app.ticketing.prompts_v2 import triage_system_instruction


def test_bcp47_language_map_and_default():
    assert bcp47_language("hi") == "hi-IN"
    assert bcp47_language("en") == "en-IN"
    assert bcp47_language("mr") == "mr-IN"
    assert bcp47_language("unknown") == "hi-IN"
    assert bcp47_language("") == "hi-IN"


def test_native_audio_model_detection():
    assert is_native_audio_model("gemini-2.5-flash-native-audio-preview-12-2025")
    assert is_native_audio_model("gemini-3.1-flash-live-preview")
    assert not is_native_audio_model("gemini-2.0-flash-live-001")


def test_live_config_matches_videosdk_vad_defaults():
    cfg = build_live_config(
        "you are a receptionist",
        language_code="hi-IN",
        voice="Puck",
        tools=triage_tools(),
        model="gemini-2.0-flash-live-001",
    )
    vad = cfg.realtime_input_config.automatic_activity_detection
    assert vad.silence_duration_ms == 400
    assert vad.prefix_padding_ms == 20
    assert "HIGH" in str(vad.end_of_speech_sensitivity)
    assert cfg.session_resumption is not None
    assert cfg.context_window_compression is not None
    assert cfg.thinking_config is None  # not a native-audio model
    assert cfg.tools


def test_live_config_thinking_budget_on_native_audio():
    cfg = build_live_config(
        "sys",
        language_code="hi-IN",
        voice="Puck",
        model="gemini-2.5-flash-native-audio-preview-12-2025",
    )
    assert cfg.thinking_config is not None
    assert cfg.thinking_config.thinking_budget == 0


def test_triage_and_consult_tool_names():
    triage = triage_tools()[0].function_declarations
    consult = consultation_tools()[0].function_declarations
    assert triage[0].name == "finish_triage"
    assert consult[0].name == "finish_consultation"
    assert "patient_name" in (triage[0].parameters.required or [])
    assert "address" in (triage[0].parameters.properties or {})
    assert "guardian_name" in (triage[0].parameters.properties or {})


def test_parse_interrupted_and_tool_call():
    sess = GeminiLiveSession()
    interrupted = SimpleNamespace(
        session_resumption_update=None,
        go_away=None,
        tool_call=None,
        server_content=SimpleNamespace(
            interrupted=True,
            interim_input_transcription=None,
            input_transcription=None,
            output_transcription=None,
            model_turn=None,
            turn_complete=False,
        ),
    )
    kinds = [e.kind for e in sess._parse(interrupted)]
    assert "interrupted" in kinds

    fc = SimpleNamespace(
        name="finish_triage",
        args={"category_key": "orthopedics", "confidence": "high"},
        id="call-1",
    )
    tool_msg = SimpleNamespace(
        session_resumption_update=None,
        go_away=None,
        tool_call=SimpleNamespace(function_calls=[fc]),
        server_content=None,
    )
    events = sess._parse(tool_msg)
    assert events[0].kind == "tool_call"
    assert events[0].tool_name == "finish_triage"
    assert events[0].tool_call_id == "call-1"


def test_parse_audio_chunk_and_user_transcript():
    sess = GeminiLiveSession()
    part = SimpleNamespace(inline_data=SimpleNamespace(data=b"\x00\x01" * 8))
    msg = SimpleNamespace(
        session_resumption_update=None,
        go_away=None,
        tool_call=None,
        server_content=SimpleNamespace(
            interrupted=False,
            interim_input_transcription=None,
            input_transcription=SimpleNamespace(text="hello ", finished=True),
            output_transcription=None,
            model_turn=SimpleNamespace(parts=[part]),
            turn_complete=True,
        ),
    )
    kinds = [e.kind for e in sess._parse(msg)]
    assert "user_speech_started" in kinds
    assert "user_transcript_final" in kinds
    assert "agent_audio_chunk" in kinds
    assert "turn_complete" in kinds


def test_triage_prompt_never_asks_department():
    cats = [TicketCategory(hospital_id="h1", key="orthopedics", label="Orthopaedics")]
    text = triage_system_instruction(cats, "hi", "female")
    assert "NEVER ask" in text
    assert "finish_triage" in text
    assert "orthopedics" in text
    assert "किस विभाग में जाना चाहती हैं?" in text
    assert "Kya aapke saath koi aaya hai?" in text
    assert "Never say \"guardian\"" in text
    assert "dohra sakti" in text


def test_triage_prompt_forbids_asking_permission_to_repeat_name():
    cats = [TicketCategory(hospital_id="h1", key="orthopedics", label="Orthopaedics")]
    text = triage_system_instruction(cats, "hi", "female")
    assert "Aapka naam Priya hai, theek hai?" in text
    assert "NEVER ask permission to repeat" in text
    assert "Unka naam kya hai?" in text


def test_merge_transcript_chunk_handles_cumulative_and_repeats():
    closing = "ठीक है। आपकी सलाह डॉक्टर तक पहुंचा दी जाएगी। धन्यवाद।"
    buf = ""
    for _ in range(7):
        buf = merge_transcript_chunk(buf, closing)
    assert buf == closing

    assert merge_transcript_chunk("Hello", "Hello world") == "Hello world"
    assert merge_transcript_chunk("Hello wo", "world") == "Hello world"


def test_sanitize_agent_transcript_strips_tool_leak_and_repeats():
    closing = "ठीक है। आपकी सलाह डॉक्टर तक पहुंचा दी जाएगी। धन्यवाद।"
    leaked = (
        "call:finish_consultation{reason:All required information gathered"
        "ठीक है। आपकी बात समझ गई। क्या आप मुझे बता सकते हैं?"
    )
    assert "finish_consultation" not in sanitize_agent_transcript(leaked)
    assert sanitize_agent_transcript(closing * 7) == closing
    assert dedupe_concatenated_repeats(closing * 3) == closing


def test_interim_input_buffered_in_user_buf():
    sess = GeminiLiveSession()
    interim_msg = SimpleNamespace(
        session_resumption_update=None,
        go_away=None,
        tool_call=None,
        server_content=SimpleNamespace(
            interrupted=False,
            interim_input_transcription=SimpleNamespace(text="namaste "),
            input_transcription=None,
            output_transcription=None,
            model_turn=None,
            turn_complete=False,
        ),
    )
    kinds = [e.kind for e in sess._parse(interim_msg)]
    assert "user_transcript_partial" in kinds
    assert sess.pending_user_text() == "namaste"


def test_turn_complete_flushes_orphaned_user_buf():
    sess = GeminiLiveSession()
    sess._user_buf = "nahi"
    msg = SimpleNamespace(
        session_resumption_update=None,
        go_away=None,
        tool_call=None,
        server_content=SimpleNamespace(
            interrupted=False,
            interim_input_transcription=None,
            input_transcription=None,
            output_transcription=None,
            model_turn=None,
            turn_complete=True,
        ),
    )
    events = sess._parse(msg)
    assert any(e.kind == "user_transcript_final" and e.text == "nahi" for e in events)


def test_force_finalize_user_clears_buffer():
    sess = GeminiLiveSession()
    sess._user_buf = "haan"
    assert sess.force_finalize_user() == "haan"
    assert sess.pending_user_text() == ""
    assert sess.force_finalize_user() == ""
