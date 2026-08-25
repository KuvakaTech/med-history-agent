"""Jan Sunwai system prompt loader — mirrors ticketing prompts_v2 language pattern."""
from __future__ import annotations

from pathlib import Path

_PROMPT_PATH = Path(__file__).resolve().parent / "prompts" / "jan_sunwai_system.txt"


def _load_base_prompt() -> str:
    if _PROMPT_PATH.is_file():
        return _PROMPT_PATH.read_text(encoding="utf-8").strip()
    return "You are the Jan Sunwai kiosk AI assistant for Varanasi District Administration."


def _language_name(code: str) -> str:
    mapping = {
        "hi": "Hindi",
        "en": "English",
        "mr": "Marathi",
        "gu": "Gujarati",
        "ta": "Tamil",
        "te": "Telugu",
        "kn": "Kannada",
        "bn": "Bengali",
        "pa": "Punjabi",
    }
    return mapping.get((code or "hi").lower(), "Hindi")


def system_instruction(language: str, phone_on_record: str | None = None) -> str:
    base = _load_base_prompt()
    lang = _language_name(language)
    # Runtime overrides base doc section 1.2 (language choice) — kiosk is Hindi-only.
    runtime = (
        f"\n\nSpeak only in {lang}. "
        "Use Hindi (Devanagari script) for everything you say aloud — it is shown live on the kiosk screen. "
        "Ask exactly ONE question per turn, then wait for the answer. "
        "NEVER ask which language the citizen prefers (no Hindi/English choice). "
        "This kiosk is Hindi-only: greet in Hindi and ask what problem they want to register."
    )
    phone_note = ""
    if phone_on_record:
        phone_note = (
            f"\nPhone already captured at intake ({phone_on_record}) — "
            "do not ask the citizen to say their phone number aloud."
        )
    return base + runtime + phone_note


def kickoff_text(language: str) -> str:
    lang = _language_name(language)
    return (
        f"The citizen is now at the kiosk. Greet them warmly in {lang} only. "
        "Do NOT ask Hindi or English — begin Jan Sunwai intake immediately. "
        "Do not wait for further instructions."
    )
