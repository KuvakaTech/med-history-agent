"""Tests for Guddi learning engine."""
from __future__ import annotations

import os

os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-for-pytest-only")

from app.kiosk.learning_engine import LearningEngine, agent_invites_repeat


def test_word_queue_from_topic():
    engine = LearningEngine("Ginti")
    assert engine.word_queue[:3] == ["ek", "do", "teen"]
    assert len(engine.word_queue) == 5


def test_cannot_finish_before_min_words():
    engine = LearningEngine("Ghar")
    assert not engine.can_finish_lesson()
    engine.taught_words = ["paani", "doodh", "roti", "ghar"]
    assert engine.can_finish_lesson()


def test_record_answer_advances_on_clear():
    engine = LearningEngine("Ginti")
    engine.on_intro_complete()
    assert engine.current_word_id() == "ek"
    done = engine.record_answer("ek", "clear")
    assert done is True
    engine.advance_word()
    assert engine.current_word_id() == "do"


def test_agent_invites_repeat_detects_bolo():
    assert agent_invites_repeat("अब तुम बोलो — पाँच!")
    assert not agent_invites_repeat("यह है पाँच।")


def test_recall_queue_first_and_middle():
    engine = LearningEngine("Ginti")
    engine.taught_words = ["ek", "do", "teen", "chaar", "paanch"]
    engine.phase = "recall"
    engine.start_recall()
    assert engine.recall_queue == ["ek", "teen"]
    assert engine.current_recall_word() == "ek"
    assert engine.expected_card_mode() == "quiz"


def test_validate_show_word_card_rejects_earlier_word():
    engine = LearningEngine("Ginti")
    engine.on_intro_complete()
    engine.sync_to_word("teen")
    err = engine.validate_show_word_card("do", "teach")
    assert err is not None
    assert "earlier" in err


def test_validate_show_word_card_accepts_forward_word():
    engine = LearningEngine("Ginti")
    engine.on_intro_complete()
    assert engine.validate_show_word_card("do", "teach") is None
    assert engine.validate_show_word_card("teen", "teach") is None


def test_sync_to_word_advances_engine_and_marks_skipped():
    engine = LearningEngine("Ginti")
    engine.on_intro_complete()
    assert engine.current_word_id() == "ek"
    ok = engine.sync_to_word("teen")
    assert ok is True
    assert engine.current_word_id() == "teen"
    assert engine.word_progress.get("do") == "not_yet"


def test_to_snapshot_roundtrip():
    engine = LearningEngine("Ghar")
    engine.on_intro_complete()
    engine.record_answer("paani", "clear")
    snap = engine.to_snapshot()
    restored = LearningEngine.from_snapshot(snap)
    assert restored.phase == engine.phase
    assert restored.word_progress == engine.word_progress


def test_words_practiced_results():
    engine = LearningEngine("Ginti")
    engine.word_progress = {"ek": "clear", "do": "emerging"}
    results = engine.words_practiced_results()
    assert len(results) == 2
    assert results[0].word == "एक"
    assert results[0].result == "clear"
