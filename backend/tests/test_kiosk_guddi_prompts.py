"""Tests for Guddi learning kiosk prompts."""
from __future__ import annotations

import os

os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-for-pytest-only")

from app.kiosk.models import KioskCentre
from app.kiosk.prompts import kickoff_text_learning, system_instruction_learning


def test_guddi_prompt_loads_with_session_inputs():
    centre = KioskCentre(
        slug="barwani-guddi",
        name="Guddi Learning",
        centre_kind="learning",
        prompt_file="guddi_learning_system.txt",
    )
    text = system_instruction_learning(centre, "hi", "Kavita", "Ghar")
    assert "GUDDI" in text.upper()
    assert "LESSON_TOPIC: Ghar" in text
    assert "LEARNER_NAME: Kavita" in text
    assert "finish_lesson" in text
    assert "NEVER invent, guess, or speak any complaint number" not in text


def test_guddi_kickoff_uses_name_and_topic():
    centre = KioskCentre(
        slug="barwani-guddi",
        name="Guddi Learning",
        centre_kind="learning",
        prompt_file="guddi_learning_system.txt",
    )
    kick = kickoff_text_learning(centre, "hi", "Kavita", "Khana")
    assert "Kavita" in kick
    assert "Khana" in kick
    assert "Guddi" in kick
