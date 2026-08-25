"""Tests for slug-based kiosk prompts."""
from __future__ import annotations

import os

os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-for-pytest-only")

from app.kiosk.models import KioskCentre, prompt_file_for_centre
from app.kiosk.prompts import kickoff_text, system_instruction


def test_jan_sunwai_prompt_loads():
    centre = KioskCentre(
        slug="varanasi-jan-sunwai",
        name="Varanasi Jan Sunwai",
        prompt_file="jan_sunwai_system.txt",
    )
    assert prompt_file_for_centre(centre) == "jan_sunwai_system.txt"
    text = system_instruction(centre, "hi")
    assert "JAN SUNWAI" in text.upper()
    assert "Speak only in Hindi" in text


def test_nagar_nigam_prompt_loads():
    centre = KioskCentre(
        slug="varanasi-nagar-nigam",
        name="Varanasi Nagar Nigam",
        prompt_file="nagar_nigam_system.txt",
        complaint_prefix="NN-VNS",
    )
    assert prompt_file_for_centre(centre) == "nagar_nigam_system.txt"
    text = system_instruction(centre, "hi")
    assert "NAGAR NIGAM" in text.upper()
    kick = kickoff_text(centre, "hi")
    assert "Nagar Nigam" in kick
    # Expanded section 6 anchors
    assert "6A" in text
    assert "PVVNL" in text
    assert "janm praman patra" in text
    assert "out_of_scope=true" in text
    assert "6G" in text
    # Hindi-only welcome (no language picker in base prompt)
    assert "English mein" not in text.split("Speak only in Hindi")[0]
    # Complaint number assigned after call, not spoken during session
    assert "NEVER invent, guess, or speak any complaint number" in text


def test_slug_defaults_without_explicit_fields():
    centre = KioskCentre(slug="varanasi-nagar-nigam", name="Varanasi Nagar Nigam")
    assert prompt_file_for_centre(centre) == "nagar_nigam_system.txt"
