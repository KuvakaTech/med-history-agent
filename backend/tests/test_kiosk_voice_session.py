"""Tests for kiosk voice session — learning verification and turn coordination."""
from __future__ import annotations

import os
from unittest.mock import AsyncMock, MagicMock, patch

os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-for-pytest-only")

import pytest

from app.kiosk import events as ev
from app.kiosk.gemini_live import LiveEvent, merge_transcript_chunk
from app.kiosk.models import KioskCentre, KioskSession
from app.kiosk.voice_session import (
    KioskVoiceSession,
    _looks_like_grievance_closing,
)


@pytest.mark.asyncio
async def test_finish_complaint_waits_for_turn_complete():
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
        tool_args={"reason": "complete", "session_type": "complaint", "print_mode": "application_letter"},
        tool_call_id="call-1",
    )
    await voice._handle_live_event(event)

    assert voice._finish_pending
    assert not voice._phase_done.is_set()
    voice._live.send_tool_response.assert_awaited_once()

    await voice._handle_live_event(LiveEvent(kind="turn_complete"))

    assert not voice._finish_pending
    assert voice._phase_done.is_set()
    assert not voice._awaiting_user


@pytest.mark.asyncio
async def test_finish_complaint_relay_still_sends_audio_before_turn_complete():
    session = KioskSession(centre_id="c1", phone="9999999999", language="hi")
    centre = KioskCentre(slug="varanasi-jan-sunwai-v3", name="Jan Sunwai v3")
    ws = MagicMock()
    ws.send_json = AsyncMock()
    voice = KioskVoiceSession(session=session, ws=ws, centre=centre)
    voice._live = MagicMock()
    voice._live.send_tool_response = AsyncMock()

    await voice._handle_live_event(
        LiveEvent(
            kind="tool_call",
            tool_name="finish_complaint",
            tool_args={"reason": "complete", "session_type": "mixed", "print_mode": "application_letter"},
            tool_call_id="call-1",
        )
    )
    assert voice._finish_pending

    await voice._handle_live_event(
        LiveEvent(kind="agent_audio_chunk", audio=b"\x00\x01" * 100)
    )

    audio_calls = [
        c for c in ws.send_json.await_args_list if c.args[0].get("type") == "agent_audio_chunk"
    ]
    assert len(audio_calls) == 1


@pytest.mark.asyncio
async def test_finish_drain_timeout_completes_phase():
    session = KioskSession(centre_id="c1", phone="9999999999", language="hi")
    centre = KioskCentre(slug="varanasi-jan-sunwai", name="Jan Sunwai")
    ws = MagicMock()
    ws.send_json = AsyncMock()
    voice = KioskVoiceSession(session=session, ws=ws, centre=centre)

    voice._request_finish()
    assert voice._finish_pending
    assert not voice._phase_done.is_set()

    with patch(
        "app.kiosk.voice_session._FINISH_DRAIN_TIMEOUT_SEC",
        0.05,
    ):
        await voice._finish_drain_timeout()

    assert voice._phase_done.is_set()
    assert not voice._finish_pending


@pytest.mark.asyncio
async def test_finish_lesson_rejected_until_enough_words():
    session = KioskSession(
        centre_id="c1",
        lesson_topic="Ginti",
        phase="lesson",
        language="hi",
    )
    centre = KioskCentre(
        slug="barwani-guddi",
        name="Guddi",
        centre_kind="learning",
    )
    ws = MagicMock()
    ws.send_json = AsyncMock()
    voice = KioskVoiceSession(session=session, ws=ws, centre=centre)
    voice._live = MagicMock()
    voice._live.send_tool_response = AsyncMock()
    voice._live.send_text = AsyncMock()

    event = LiveEvent(
        kind="tool_call",
        tool_name="finish_lesson",
        tool_args={"reason": "complete"},
        tool_call_id="call-early",
    )
    await voice._handle_live_event(event)

    assert not voice._phase_done.is_set()
    voice._live.send_tool_response.assert_awaited_once()
    assert "error" in voice._live.send_tool_response.await_args.args[2]
    voice._live.send_text.assert_awaited_once()


@pytest.mark.asyncio
async def test_finish_lesson_allowed_after_enough_words():
    session = KioskSession(
        centre_id="c1",
        lesson_topic="Ginti",
        phase="lesson",
        language="hi",
    )
    centre = KioskCentre(
        slug="barwani-guddi",
        name="Guddi",
        centre_kind="learning",
    )
    ws = MagicMock()
    ws.send_json = AsyncMock()
    voice = KioskVoiceSession(session=session, ws=ws, centre=centre)
    voice._live = MagicMock()
    voice._live.send_tool_response = AsyncMock()
    assert voice._learning_engine is not None
    voice._learning_engine.taught_words = ["ek", "do", "teen", "chaar"]

    event = LiveEvent(
        kind="tool_call",
        tool_name="finish_lesson",
        tool_args={"reason": "complete"},
        tool_call_id="call-done",
    )
    await voice._handle_live_event(event)

    assert voice._phase_done.is_set()


@pytest.mark.asyncio
async def test_show_word_card_emits_ws_event():
    session = KioskSession(
        centre_id="c1",
        lesson_topic="Khana",
        phase="lesson",
        language="hi",
    )
    centre = KioskCentre(
        slug="barwani-guddi",
        name="Guddi",
        centre_kind="learning",
    )
    ws = MagicMock()
    ws.send_json = AsyncMock()
    voice = KioskVoiceSession(session=session, ws=ws, centre=centre)
    voice._live = MagicMock()
    voice._live.send_tool_response = AsyncMock()

    event = LiveEvent(
        kind="tool_call",
        tool_name="show_word_card",
        tool_args={"word_id": "aam", "mode": "quiz"},
        tool_call_id="call-3",
    )
    await voice._handle_show_word_card(event)

    assert voice._awaiting_child_answer is True
    assert voice._displayed_card == {"word_id": "aam", "mode": "quiz"}
    ws.send_json.assert_awaited()
    payload = ws.send_json.await_args.args[0]
    assert payload["type"] == "show_word_card"
    assert payload["word_id"] == "aam"
    voice._live.send_tool_response.assert_awaited_once()


@pytest.mark.asyncio
async def test_quiz_wrong_answer_injects_incorrect_hint():
    session = KioskSession(
        centre_id="c1",
        lesson_topic="Khana",
        phase="lesson",
        language="hi",
    )
    centre = KioskCentre(
        slug="barwani-guddi",
        name="Guddi",
        centre_kind="learning",
    )
    ws = MagicMock()
    ws.send_json = AsyncMock()
    voice = KioskVoiceSession(session=session, ws=ws, centre=centre)
    voice._live = MagicMock()
    voice._live.send_text = AsyncMock()
    voice._displayed_card = {"word_id": "aam", "mode": "quiz"}
    voice._awaiting_child_answer = True
    voice._awaiting_user = True
    voice._agent_turn_id = 1

    await voice._process_child_answer("xyz totally wrong")

    voice._live.send_text.assert_awaited_once()
    hint = voice._live.send_text.await_args.args[0]
    assert "INCORRECT" in hint
    payload = ws.send_json.await_args.args[0]
    assert payload["type"] == "word_answer_result"
    assert payload["result"] == "wrong"


@pytest.mark.asyncio
async def test_teach_mode_wrong_answer_sends_incorrect_hint():
    session = KioskSession(
        centre_id="c1",
        lesson_topic="Ginti",
        phase="lesson",
        language="hi",
    )
    centre = KioskCentre(
        slug="barwani-guddi",
        name="Guddi",
        centre_kind="learning",
    )
    ws = MagicMock()
    ws.send_json = AsyncMock()
    voice = KioskVoiceSession(session=session, ws=ws, centre=centre)
    voice._live = MagicMock()
    voice._live.send_text = AsyncMock()
    voice._displayed_card = {"word_id": "paanch", "mode": "teach"}
    voice._awaiting_child_answer = True
    voice._awaiting_user = True
    voice._agent_turn_id = 2

    await voice._process_child_answer("आठ")

    hint_calls = [c.args[0] for c in voice._live.send_text.await_args_list]
    assert any("INCORRECT" in h for h in hint_calls)
    payload = ws.send_json.await_args.args[0]
    assert payload["result"] == "wrong"


@pytest.mark.asyncio
async def test_teach_mode_correct_answer_sends_correct_hint():
    session = KioskSession(
        centre_id="c1",
        lesson_topic="Shareer",
        phase="lesson",
        language="hi",
    )
    centre = KioskCentre(
        slug="barwani-guddi",
        name="Guddi",
        centre_kind="learning",
    )
    ws = MagicMock()
    ws.send_json = AsyncMock()
    voice = KioskVoiceSession(session=session, ws=ws, centre=centre)
    voice._live = MagicMock()
    voice._live.send_text = AsyncMock()
    voice._displayed_card = {"word_id": "aankh", "mode": "teach"}
    voice._awaiting_child_answer = True
    voice._awaiting_user = True
    voice._agent_turn_id = 1

    await voice._process_child_answer("aankh")

    hint_calls = [c.args[0] for c in voice._live.send_text.await_args_list]
    assert any("CORRECT" in h for h in hint_calls)


@pytest.mark.asyncio
async def test_auto_show_card_on_agent_final_speech():
    session = KioskSession(
        centre_id="c1",
        lesson_topic="Rang",
        phase="lesson",
        language="hi",
    )
    centre = KioskCentre(
        slug="barwani-guddi",
        name="Guddi",
        centre_kind="learning",
    )
    ws = MagicMock()
    ws.send_json = AsyncMock()
    voice = KioskVoiceSession(session=session, ws=ws, centre=centre)
    session.turn_count = 1

    await voice._maybe_auto_show_card(
        "ये देखो लाल रंग! टमाटर जैसा लाल. बोलो मेरे साथ - लाल."
    )

    ws.send_json.assert_awaited_once()
    payload = ws.send_json.await_args.args[0]
    assert payload["type"] == "show_word_card"
    assert payload["word_id"] == "laal"
    assert voice._displayed_card == {"word_id": "laal", "mode": "teach"}


@pytest.mark.asyncio
async def test_auto_show_blocked_while_awaiting_same_word():
    """No duplicate card emit when agent repeats the word already on screen."""
    session = KioskSession(
        centre_id="c1",
        lesson_topic="Ginti",
        phase="lesson",
        language="hi",
    )
    centre = KioskCentre(
        slug="barwani-guddi",
        name="Guddi",
        centre_kind="learning",
    )
    ws = MagicMock()
    ws.send_json = AsyncMock()
    voice = KioskVoiceSession(session=session, ws=ws, centre=centre)
    assert voice._learning_engine is not None
    voice._learning_engine.on_intro_complete()
    session.turn_count = 2
    voice._displayed_card = {"word_id": "ek", "mode": "teach"}
    voice._awaiting_child_answer = True

    await voice._maybe_auto_show_card("एक देखो।")

    ws.send_json.assert_not_awaited()
    assert voice._displayed_card["word_id"] == "ek"


@pytest.mark.asyncio
async def test_show_word_card_allowed_when_guddi_moves_forward():
    session = KioskSession(
        centre_id="c1",
        lesson_topic="Ginti",
        phase="lesson",
        language="hi",
    )
    centre = KioskCentre(
        slug="barwani-guddi",
        name="Guddi",
        centre_kind="learning",
    )
    ws = MagicMock()
    ws.send_json = AsyncMock()
    voice = KioskVoiceSession(session=session, ws=ws, centre=centre)
    voice._live = MagicMock()
    voice._live.send_tool_response = AsyncMock()
    voice._live.send_text = AsyncMock()
    assert voice._learning_engine is not None
    voice._learning_engine.on_intro_complete()
    voice._displayed_card = {"word_id": "ek", "mode": "teach"}
    voice._awaiting_child_answer = True

    event = LiveEvent(
        kind="tool_call",
        tool_name="show_word_card",
        tool_args={"word_id": "teen", "mode": "teach"},
        tool_call_id="call-forward",
    )
    await voice._handle_show_word_card(event)

    voice._live.send_tool_response.assert_awaited_once()
    assert "result" in voice._live.send_tool_response.await_args.args[2]
    assert voice._displayed_card["word_id"] == "teen"


@pytest.mark.asyncio
async def test_stale_user_transcript_ignored_when_not_awaiting_user():
    session = KioskSession(
        centre_id="c1",
        lesson_topic="Ginti",
        phase="lesson",
        language="hi",
    )
    centre = KioskCentre(
        slug="barwani-guddi",
        name="Guddi",
        centre_kind="learning",
    )
    ws = MagicMock()
    ws.send_json = AsyncMock()
    voice = KioskVoiceSession(session=session, ws=ws, centre=centre)
    voice._live = MagicMock()
    voice._live.send_text = AsyncMock()
    voice._displayed_card = {"word_id": "ek", "mode": "teach"}
    voice._awaiting_child_answer = True
    voice._awaiting_user = False

    await voice._handle_user_transcript_final("एक")

    answer_calls = [
        c
        for c in ws.send_json.await_args_list
        if c.args[0].get("type") == "word_answer_result"
    ]
    assert len(answer_calls) == 0


@pytest.mark.asyncio
async def test_agent_invite_sets_awaiting_child_answer():
    session = KioskSession(
        centre_id="c1",
        lesson_topic="Ginti",
        phase="lesson",
        language="hi",
    )
    centre = KioskCentre(
        slug="barwani-guddi",
        name="Guddi",
        centre_kind="learning",
    )
    ws = MagicMock()
    ws.send_json = AsyncMock()
    voice = KioskVoiceSession(session=session, ws=ws, centre=centre)
    voice._displayed_card = {"word_id": "ek", "mode": "teach"}
    voice._awaiting_child_answer = False

    await voice._on_agent_transcript_final("यह है एक। अब तुम बोलो — एक!")

    assert voice._awaiting_child_answer is True


def test_merge_transcript_chunk_cumulative():
    buf = "नमस्ते"
    merged = merge_transcript_chunk(buf, "नमस्ते मैं")
    assert merged == "नमस्ते मैं"


@pytest.mark.asyncio
async def test_intro_emits_first_word_card():
    session = KioskSession(
        centre_id="c1",
        lesson_topic="Ginti",
        phase="lesson",
        language="hi",
    )
    centre = KioskCentre(
        slug="barwani-guddi",
        name="Guddi",
        centre_kind="learning",
    )
    ws = MagicMock()
    ws.send_json = AsyncMock()
    voice = KioskVoiceSession(session=session, ws=ws, centre=centre)
    voice._live = MagicMock()
    voice._live.send_text = AsyncMock()
    voice._awaiting_user = True

    await voice._handle_user_transcript_final("मैं खुश हूँ")

    card_calls = [
        c for c in ws.send_json.await_args_list if c.args[0].get("type") == "show_word_card"
    ]
    assert len(card_calls) == 1
    assert card_calls[0].args[0]["word_id"] == "ek"
    assert session.lesson_state is not None
    assert session.lesson_state["phase"] == "warmup"


@pytest.mark.asyncio
async def test_auto_show_fallback_when_expected_card_missing():
    session = KioskSession(
        centre_id="c1",
        lesson_topic="Ginti",
        phase="lesson",
        language="hi",
    )
    centre = KioskCentre(
        slug="barwani-guddi",
        name="Guddi",
        centre_kind="learning",
    )
    ws = MagicMock()
    ws.send_json = AsyncMock()
    voice = KioskVoiceSession(session=session, ws=ws, centre=centre)
    assert voice._learning_engine is not None
    voice._learning_engine.on_intro_complete()
    session.turn_count = 1
    voice._displayed_card = None

    await voice._maybe_auto_show_card("आज हम सीखेंगे एक।")

    ws.send_json.assert_awaited_once()
    assert voice._displayed_card == {"word_id": "ek", "mode": "teach"}


@pytest.mark.asyncio
async def test_auto_show_updates_card_when_guddi_moves_ahead():
    """Card must update when Guddi names the next word while still on previous card."""
    session = KioskSession(
        centre_id="c1",
        lesson_topic="Ginti",
        phase="lesson",
        language="hi",
    )
    centre = KioskCentre(
        slug="barwani-guddi",
        name="Guddi",
        centre_kind="learning",
    )
    ws = MagicMock()
    ws.send_json = AsyncMock()
    voice = KioskVoiceSession(session=session, ws=ws, centre=centre)
    assert voice._learning_engine is not None
    voice._learning_engine.on_intro_complete()
    voice._learning_engine.sync_to_word("do")
    session.turn_count = 2
    voice._displayed_card = {"word_id": "do", "mode": "teach"}
    voice._awaiting_child_answer = True

    await voice._maybe_auto_show_card(
        "कोई बात नहीं, चलो अगला मजेदार शब्द! ये है तीन। अब तुम बोलो - तीन।"
    )

    ws.send_json.assert_awaited_once()
    payload = ws.send_json.await_args.args[0]
    assert payload["word_id"] == "teen"
    assert voice._displayed_card == {"word_id": "teen", "mode": "teach"}
    assert voice._learning_engine.current_word_id() == "teen"


@pytest.mark.asyncio
async def test_auto_show_blocked_when_correct_card_already_shown():
    session = KioskSession(
        centre_id="c1",
        lesson_topic="Ginti",
        phase="lesson",
        language="hi",
    )
    centre = KioskCentre(
        slug="barwani-guddi",
        name="Guddi",
        centre_kind="learning",
    )
    ws = MagicMock()
    ws.send_json = AsyncMock()
    voice = KioskVoiceSession(session=session, ws=ws, centre=centre)
    assert voice._learning_engine is not None
    voice._learning_engine.on_intro_complete()
    session.turn_count = 1
    voice._displayed_card = {"word_id": "ek", "mode": "teach"}

    await voice._maybe_auto_show_card("एक देखो।")

    ws.send_json.assert_not_awaited()


@pytest.mark.asyncio
async def test_tool_rejected_for_earlier_engine_word():
    session = KioskSession(
        centre_id="c1",
        lesson_topic="Ginti",
        phase="lesson",
        language="hi",
    )
    centre = KioskCentre(
        slug="barwani-guddi",
        name="Guddi",
        centre_kind="learning",
    )
    ws = MagicMock()
    ws.send_json = AsyncMock()
    voice = KioskVoiceSession(session=session, ws=ws, centre=centre)
    voice._live = MagicMock()
    voice._live.send_tool_response = AsyncMock()
    voice._live.send_text = AsyncMock()
    assert voice._learning_engine is not None
    voice._learning_engine.on_intro_complete()
    voice._learning_engine.sync_to_word("teen")

    event = LiveEvent(
        kind="tool_call",
        tool_name="show_word_card",
        tool_args={"word_id": "do", "mode": "teach"},
        tool_call_id="call-wrong",
    )
    await voice._handle_show_word_card(event)

    voice._live.send_tool_response.assert_awaited_once()
    assert "error" in voice._live.send_tool_response.await_args.args[2]


def test_session_processing_event():
    payload = ev.session_processing("sess-abc")
    assert payload == {"type": "session_processing", "session_id": "sess-abc"}


def test_looks_like_grievance_closing():
    closing = (
        "कोई बात नहीं जी। जितनी जानकारी आपने दी है, मैं उसे नोट कर लेती हूँ। "
        "जन सुनवाई में आने के लिए धन्यवाद। आपका दिन शुभ हो।"
    )
    assert _looks_like_grievance_closing(closing)
    assert not _looks_like_grievance_closing("आपका नाम क्या है?")


@pytest.mark.asyncio
async def test_auto_finish_on_closing_transcript_waits_for_turn_complete():
    session = KioskSession(centre_id="c1", phone="9999999999", language="hi")
    centre = KioskCentre(slug="barwani-jan-sunwai", name="Barwani Jan Sunwai")
    ws = MagicMock()
    ws.send_json = AsyncMock()
    voice = KioskVoiceSession(session=session, ws=ws, centre=centre)

    closing = (
        "कोई बात नहीं जी। जन सुनवाई में आने के लिए धन्यवाद। आपका दिन शुभ हो।"
    )
    event = LiveEvent(kind="agent_transcript_final", text=closing)
    await voice._handle_live_event(event)

    assert voice._finish_pending
    assert not voice._phase_done.is_set()

    await voice._handle_live_event(LiveEvent(kind="turn_complete"))
    assert voice._phase_done.is_set()


@pytest.mark.asyncio
async def test_ignores_agent_events_after_phase_done():
    session = KioskSession(centre_id="c1", phone="9999999999", language="hi")
    centre = KioskCentre(slug="barwani-jan-sunwai", name="Barwani Jan Sunwai")
    ws = MagicMock()
    ws.send_json = AsyncMock()
    voice = KioskVoiceSession(session=session, ws=ws, centre=centre)
    voice._phase_done.set()

    event = LiveEvent(kind="agent_transcript_partial", text="धन्यवाद। आपका दिन शुभ हो।")
    await voice._handle_live_event(event)

    ws.send_json.assert_not_awaited()
