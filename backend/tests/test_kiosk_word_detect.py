"""Tests for vocabulary word detection in agent speech."""
from __future__ import annotations

import os

os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-for-pytest-only")

from app.kiosk.word_detect import detect_word_in_speech, should_update_card


def test_detect_laal_in_rang_lesson():
    text = "ये देखो लाल रंग! टमाटर जैसा लाल. बोलो मेरे साथ - लाल."
    result = detect_word_in_speech(text, "Rang")
    assert result is not None
    assert result[0] == "laal"
    assert result[1] == "teach"


def test_detect_aam_quiz():
    result = detect_word_in_speech("यह क्या है? आम देखो।", "Khana")
    assert result is not None
    assert result[0] == "aam"
    assert result[1] == "teach"


def test_detect_no_match():
    assert detect_word_in_speech("Namaste! Aaj tum kaise ho?", "Rang") is None


def test_detect_do_not_inside_dost():
    intro = (
        "नमस्ते! मैं गुड्डी हूँ - तुम्हारी दोस्त। "
        "आज हम साथ में खेलेंगे और कुछ नए शब्द बोलेंगे।"
    )
    assert detect_word_in_speech(intro, "Ginti") is None


def test_detect_do_when_spoken_alone():
    result = detect_word_in_speech("आज हम सीखेंगे दो। बोलो मेरे साथ — दो!", "Ginti")
    assert result is not None
    assert result[0] == "do"


def test_should_update_new_word():
    assert should_update_card(("peela", "teach"), "laal", "teach") is True


def test_should_not_update_same_word():
    assert should_update_card(("laal", "teach"), "laal", "teach") is False
