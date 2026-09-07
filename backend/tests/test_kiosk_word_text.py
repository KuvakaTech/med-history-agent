"""Tests for whole-word vocabulary text matching."""
from __future__ import annotations

import os

os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-for-pytest-only")

from app.kiosk.word_text import text_contains_variant


def test_do_not_inside_dost():
    intro = "नमस्ते! मैं गुड्डी हूँ - तुम्हारी दोस्त।"
    assert text_contains_variant(intro, "दो") is False
    assert text_contains_variant(intro, "do") is False


def test_do_as_whole_word():
    lesson = "आज हम सीखेंगे दो। बोलो मेरे साथ — दो!"
    assert text_contains_variant(lesson, "दो") is True
