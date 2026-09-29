from app.ticketing.intake_locale import (
    normalize_kiosk_language,
    triage_voice_persona,
)


def test_normalize_defaults_unknown_to_hi():
    assert normalize_kiosk_language("xx") == "hi"
    assert normalize_kiosk_language("en") == "en"


def test_english_triage_persona_no_hindi():
    text = triage_voice_persona("en")
    assert "English" in text
    assert "Devanagari" not in text
