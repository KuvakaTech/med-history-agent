"""Structured event constants and payload builders for WS/SSE transport.

These are the "webhook v2" events — not outbound webhooks to external URLs,
but structured event types pushed over the existing WS transport so the FE
state machine reacts correctly.
"""
from __future__ import annotations

from typing import Any, Optional

# Event type constants
TRIAGE_STARTED = "triage_started"
CATEGORY_IDENTIFIED = "category_identified"
CATEGORY_MANUAL_REQUIRED = "category_manual_required"
CATEGORY_CONFIRMED = "category_confirmed"
CONSULTATION_STARTED = "consultation_started"
RED_FLAG_RAISED = "red_flag_raised"
CONSULTATION_ENDED = "consultation_ended"
RESULT_READY = "result_ready"
SESSION_PARTIAL = "session_partial"

# Standard streaming events
PARTIAL_TRANSCRIPT = "partial_transcript"
AGENT_SPEAKING = "agent_speaking"
AGENT_DONE_SPEAKING = "agent_done_speaking"
TURN_COMPLETE = "turn_complete"
ERROR = "error"


def triage_started(session_id: str, language: str) -> dict:
    return {"type": TRIAGE_STARTED, "session_id": session_id, "language": language}


def category_identified(key: str, label: str, confidence: str) -> dict:
    return {
        "type": CATEGORY_IDENTIFIED,
        "category": {"key": key, "label": label},
        "confidence": confidence,
    }


def category_manual_required(available_categories: list[dict]) -> dict:
    return {
        "type": CATEGORY_MANUAL_REQUIRED,
        "categories": available_categories,
    }


def category_confirmed(key: str, label: str, source: str) -> dict:
    return {
        "type": CATEGORY_CONFIRMED,
        "category": {"key": key, "label": label, "source": source},
    }


def consultation_started(category_key: str, turn: int) -> dict:
    return {
        "type": CONSULTATION_STARTED,
        "category": category_key,
        "starting_turn": turn,
    }


def red_flag_raised(flag_type: str, description: str) -> dict:
    return {
        "type": RED_FLAG_RAISED,
        "flag": {"flag_type": flag_type, "description": description},
    }


def consultation_ended() -> dict:
    return {"type": CONSULTATION_ENDED}


def result_ready(summary: Any, flags: list[dict]) -> dict:
    return {"type": RESULT_READY, "summary": summary, "flags": flags}


def session_partial(session_id: str) -> dict:
    return {"type": SESSION_PARTIAL, "session_id": session_id}


def error(message: str, fatal: bool = False) -> dict:
    return {"type": ERROR, "message": message, "fatal": fatal}


def partial_transcript(text: str) -> dict:
    return {"type": PARTIAL_TRANSCRIPT, "text": text}


def agent_speaking(question: str, turn: int) -> dict:
    return {"type": AGENT_SPEAKING, "question": question, "turn": turn}


def agent_done_speaking(turn: int) -> dict:
    return {"type": AGENT_DONE_SPEAKING, "turn": turn}


def turn_complete(
    turn: int,
    next_question: Optional[str],
    phase: str,
    history_complete: bool,
    new_flags: list[dict],
) -> dict:
    return {
        "type": TURN_COMPLETE,
        "turn": turn,
        "next_question": next_question,
        "phase": phase,
        "history_complete": history_complete,
        "new_flags": new_flags,
    }
