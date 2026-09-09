"""WS event builders for kiosk voice sessions."""
from __future__ import annotations

from typing import Any, Optional


def ready(
    session_id: str,
    phase: str,
    language: str,
    voice_mode: str = "gemini_live",
) -> dict:
    return {
        "type": "ready",
        "session_id": session_id,
        "phase": phase,
        "language": language,
        "voice_mode": voice_mode,
    }


def complaint_started(session_id: str, language: str) -> dict:
    return {
        "type": "complaint_started",
        "session_id": session_id,
        "language": language,
    }


def lesson_started(session_id: str, language: str) -> dict:
    return {
        "type": "lesson_started",
        "session_id": session_id,
        "language": language,
    }


def result_ready(
    complaint_number: str = "",
    grievance: Optional[dict] = None,
    learning_record: Optional[dict] = None,
) -> dict:
    payload: dict[str, Any] = {"type": "result_ready"}
    if learning_record is not None:
        payload["learning_record"] = learning_record
    else:
        g = grievance or {}
        payload["complaint_number"] = complaint_number
        payload["grievance"] = g
        payload["session_type"] = g.get("session_type")
        payload["print_mode"] = g.get("print_mode")
        payload["print_document_text"] = g.get("print_document_text")
    return payload


def session_processing(session_id: str) -> dict:
    return {"type": "session_processing", "session_id": session_id}


def session_partial(session_id: str) -> dict:
    return {"type": "session_partial", "session_id": session_id}


def error(message: str, fatal: bool = False) -> dict:
    return {"type": "error", "message": message, "fatal": fatal}


def partial_transcript(text: str) -> dict:
    return {"type": "partial_transcript", "text": text}


def agent_speaking(question: str, turn: int) -> dict:
    return {"type": "agent_speaking", "question": question, "turn": turn}


def agent_done_speaking(turn: int) -> dict:
    return {"type": "agent_done_speaking", "turn": turn}


def agent_audio_chunk(audio_b64: str) -> dict:
    return {
        "type": "agent_audio_chunk",
        "audio_b64": audio_b64,
        "mime": "audio/pcm;rate=24000",
    }


def interrupt() -> dict:
    return {"type": "interrupt"}


def show_word_card(
    word_id: str,
    hindi: str,
    image_url: str,
    mode: str,
) -> dict:
    return {
        "type": "show_word_card",
        "word_id": word_id,
        "hindi": hindi,
        "image_url": image_url,
        "mode": mode,
    }


def word_answer_result(
    word_id: str,
    child_said: str,
    result: str,
    expected_hindi: str,
) -> dict:
    return {
        "type": "word_answer_result",
        "word_id": word_id,
        "child_said": child_said,
        "result": result,
        "expected_hindi": expected_hindi,
    }


def user_speech_started() -> dict:
    return {"type": "user_speech_started"}
