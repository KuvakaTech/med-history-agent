"""Tests for kiosk vocabulary answer matcher."""
from __future__ import annotations

import os

os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-for-pytest-only")

from app.kiosk.vocabulary import get_word
from app.kiosk.word_matcher import answer_hint, match_answer


def test_match_aam_clear_roman():
    assert match_answer("aam", "aam") == "clear"


def test_match_aam_clear_devanagari():
    assert match_answer("आम", "aam") == "clear"


def test_match_aam_close_misspelling():
    assert match_answer("am", "aam") == "clear"  # "am" is in accept list


def test_match_aam_wrong_answer():
    assert match_answer("roti kela", "aam") == "wrong"


def test_match_ginti_no_cross_number_fuzzy():
    assert match_answer("आठ", "paanch") == "wrong"
    assert match_answer("तीन", "ek") == "wrong"
    assert match_answer("", "aam") == "wrong"


def test_match_hara_rejects_heera_confusion():
    assert match_answer("heera", "hara") == "wrong"
    assert match_answer("हीरा", "hara") == "wrong"
    assert match_answer("haara", "hara") == "clear"
    assert match_answer("hara", "hara") == "clear"


def test_match_unknown_word_id():
    assert match_answer("aam", "notaword") == "wrong"


def test_answer_hint_incorrect():
    hint = answer_hint("wrong", get_word("aam"), "daal")
    assert "INCORRECT" in hint
    assert "आम" in hint


def test_answer_hint_correct():
    hint = answer_hint("clear", get_word("aam"), "aam")
    assert "CORRECT" in hint
