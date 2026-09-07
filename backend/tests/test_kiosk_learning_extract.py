"""Tests for learning record extract with engine snapshot."""
from __future__ import annotations

import os
from unittest.mock import AsyncMock, patch

os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-for-pytest-only")

import pytest

from app.kiosk.learning_extract import _engine_words_from_snapshot, run_learning_extract
from app.kiosk.models import KioskCentre, KioskSession, KioskTranscriptEntry


def test_engine_words_from_snapshot():
    session = KioskSession(
        centre_id="c1",
        lesson_topic="Ginti",
        phase="lesson",
        lesson_state={
            "phase": "teach",
            "topic": "Ginti",
            "word_queue": ["ek", "do"],
            "current_index": 1,
            "word_attempts": 0,
            "taught_words": ["ek"],
            "word_progress": {"ek": "clear", "do": "emerging"},
            "recall_queue": [],
            "recall_index": -1,
        },
    )
    words, clear_n, emerging_n = _engine_words_from_snapshot(session)
    assert len(words) == 2
    assert clear_n == 1
    assert emerging_n == 1


@pytest.mark.asyncio
async def test_extract_prefers_engine_words_over_llm():
    session = KioskSession(
        centre_id="c1",
        lesson_topic="Ginti",
        phase="lesson",
        learner_name="Riya",
        lesson_state={
            "phase": "teach",
            "topic": "Ginti",
            "word_queue": ["ek", "do"],
            "current_index": 1,
            "word_attempts": 0,
            "taught_words": ["ek", "do"],
            "word_progress": {"ek": "clear", "do": "not_yet"},
            "recall_queue": [],
            "recall_index": -1,
        },
        transcript=[
            KioskTranscriptEntry(speaker="agent", text="Namaste"),
            KioskTranscriptEntry(speaker="user", text="khush"),
        ],
    )
    centre = KioskCentre(
        slug="barwani-guddi",
        name="Guddi",
        centre_kind="learning",
    )

    class FakeExtract:
        learner_name = None
        mode_used = None
        mood_start = "happy"
        topic = None
        words_practiced = []
        new_words_clear = 0
        emerging_words = 0
        pronunciation_note = None
        dialect_bridges = []
        milestone_signal = None
        engagement = "high"
        flags = "none"
        next_focus = []
        friendly_summary = "Great session"

    with patch(
        "app.kiosk.learning_extract.llm.complete_structured",
        new_callable=AsyncMock,
        return_value=FakeExtract(),
    ), patch(
        "app.kiosk.learning_extract.kiosk_session_store.update",
        new_callable=AsyncMock,
    ):
        result = await run_learning_extract(session, centre)

    assert result.learning_record is not None
    assert len(result.learning_record.words_practiced) == 2
    assert result.learning_record.new_words_clear == 1
    assert result.learning_record.emerging_words == 0
    assert result.learning_record.mood_start == "happy"
