"""Tests for Roman Hindi → Devanagari display captions."""
from __future__ import annotations

import os

os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-for-pytest-only")

from app.kiosk.hindi_display import to_devanagari_display


def test_roman_greeting_becomes_devanagari():
    text = "Namaste ji, aap kya samasya darj karana chahte hain"
    out = to_devanagari_display(text)
    assert "नमस्ते" in out
    assert "Aap" not in out and "Namaste" not in out


def test_already_devanagari_passthrough():
    text = "नमस्ते जी, आप क्या समस्या दर्ज करना चाहते हैं?"
    assert to_devanagari_display(text) == text
