"""Tests for clinical answer validation heuristics."""
from __future__ import annotations

import os

os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-for-pytest-only")

from app.clinical.questionnaire.answer_validation import is_skip_answer, is_valid_answer


def test_skip_phrase_is_valid():
    assert is_skip_answer("I'd prefer to skip this question.")
    assert is_valid_answer("I'd prefer to skip this question.")


def test_empty_answer_rejected():
    assert not is_valid_answer("")
    assert not is_valid_answer("   ")


def test_junk_tokens_rejected():
    assert not is_valid_answer("[inaudible]")
    assert not is_valid_answer("(silence)")
    assert not is_valid_answer(".")


def test_short_numeric_severity_accepted():
    assert is_valid_answer("7")
    assert is_valid_answer("8/10")


def test_single_non_numeric_char_rejected():
    assert not is_valid_answer("a")


def test_substantive_answer_accepted():
    assert is_valid_answer("About three days ago")
    assert is_valid_answer("It hurts when I walk")
