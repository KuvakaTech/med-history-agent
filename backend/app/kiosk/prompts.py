"""Kiosk system prompt loader — centre slug selects voice agent context."""
from __future__ import annotations

from pathlib import Path

from app.kiosk.models import KioskCentre, prompt_file_for_centre

_PROMPTS_DIR = Path(__file__).resolve().parent / "prompts"


def _load_base_prompt(centre: KioskCentre) -> str:
    path = _PROMPTS_DIR / prompt_file_for_centre(centre)
    if path.is_file():
        return path.read_text(encoding="utf-8").strip()
    return f"You are the kiosk AI assistant for {centre.name}."


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


def system_instruction(
    centre: KioskCentre,
    language: str,
    phone_on_record: str | None = None,
) -> str:
    base = _load_base_prompt(centre)
    lang = _language_name(language)
    runtime = (
        f"\n\nSpeak only in {lang}. "
        "Use Hindi (Devanagari script) for everything you say aloud — it is shown live on the kiosk screen. "
        "Ask exactly ONE question per turn, then wait for the answer. "
        "NEVER ask which language the citizen prefers (no Hindi/English choice). "
        "This kiosk is Hindi-only: greet in Hindi and ask what problem they want to register. "
        "CRITICAL — COMPLAINT NUMBER: You do NOT know the complaint number during this call. "
        "NEVER invent, guess, or speak any complaint number (no JS-VNS-, NN-VNS-, NNVNS-, or random digits). "
        "The system assigns the official number automatically ONLY after the citizen ends the call; "
        "it then appears on the result screen. During the call, only say the number will appear on screen when they finish."
    )
    phone_note = ""
    if phone_on_record:
        phone_note = (
            f"\nPhone already captured at intake ({phone_on_record}) — "
            "do not ask the citizen to say their phone number aloud."
        )
    return base + runtime + phone_note


def kickoff_text(centre: KioskCentre, language: str) -> str:
    lang = _language_name(language)
    return (
        f"The citizen is now at the kiosk for {centre.name}. "
        f"Greet them warmly in {lang} only. "
        "Do NOT ask Hindi or English — begin intake immediately. "
        "Do not wait for further instructions."
    )
