"""Tests for vocabulary topic helpers."""
from __future__ import annotations

import os

os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-for-pytest-only")

from app.kiosk.vocabulary import (
    first_word_for_topic,
    get_word_for_lesson,
    topic_cover_image,
)
from app.kiosk.word_detect import detect_word_in_speech


def test_roti_image_uses_khana_folder():
    w = get_word_for_lesson("roti", "Khana")
    assert w is not None
    assert w.image == "/kiosk/vocabulary/khana/roti.jpg"


def test_roti_image_uses_ghar_folder():
    w = get_word_for_lesson("roti", "Ghar")
    assert w is not None
    assert w.image == "/kiosk/vocabulary/ghar/roti.jpg"


def test_first_word_per_topic():
    assert first_word_for_topic("Ghar") == "paani"
    assert first_word_for_topic("Khana") == "roti"
    assert first_word_for_topic("Rang") == "laal"
    assert first_word_for_topic("Guddi-choose") is None


def test_topic_covers():
    assert "ghar" in topic_cover_image("Ghar")
    assert "aam" in topic_cover_image("Khana")
    assert "laal" in topic_cover_image("Rang")


def test_detect_all_topics_sample():
    samples = [
        ("Rang", "लाल रंग देखो", "laal"),
        ("Khana", "यह आम है", "aam"),
        ("Ghar", "यह पानी है", "paani"),
        ("Jaanwar", "बकरी देखो", "bakri"),
        ("Ginti", "एक बोलो", "ek"),
        ("Shareer", "आँख देखो", "aankh"),
    ]
    for topic, text, expected in samples:
        result = detect_word_in_speech(text, topic)
        assert result is not None, f"failed for {topic}"
        assert result[0] == expected
