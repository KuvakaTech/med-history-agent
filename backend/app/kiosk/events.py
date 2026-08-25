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


def result_ready(complaint_number: str, grievance: dict) -> dict:
    return {
        "type": "result_ready",
        "complaint_number": complaint_number,
        "grievance": grievance,
    }


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


def user_speech_started() -> dict:
    return {"type": "user_speech_started"}
