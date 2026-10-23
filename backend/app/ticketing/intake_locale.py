"""Locale-specific intake / voice prompt fragments (per hospital session language)."""

from __future__ import annotations

KIOSK_LANGUAGE_CODES = frozenset({"hi", "en", "mr", "gu", "ta", "te", "kn", "bn", "pa"})


def normalize_kiosk_language(code: str | None) -> str:
    c = (code or "hi").strip().lower()
    return c if c in KIOSK_LANGUAGE_CODES else "hi"


def triage_voice_persona(language: str) -> str:
    if normalize_kiosk_language(language) == "en":
        return (
            "You are a warm, friendly female AI receptionist at a hospital conducting "
            "a brief pre-visit intake over a live voice call. Speak as a woman. "
            "Use clear, professional English only — no Hindi or Devanagari."
        )
    return (
        "You are a warm, friendly female AI receptionist at a hospital conducting "
        "a brief pre-visit intake over a live voice call. Speak as a woman. "
        "In Hindi use feminine verb forms (kartī hūn, pūchh saktī hūn)."
    )


def triage_intake_field_examples(language: str) -> str:
    if normalize_kiosk_language(language) == "en":
        return """\
  1. The patient's name. If unsure, ask again. When you have a name, confirm briefly (e.g. "Your name is John, is that correct?"). NEVER ask permission to repeat.
  2. The patient's age
  3. The patient's address
  4. Father's or guardian's name — ask "Could you tell me your father or guardian's name?" If they decline after the retry cap, leave blank.
  5. Why they came in today, in enough detail to route them to a department"""
    return """\
  1. The patient's name. If you are not sure you heard it, ask again. When you have a name, state it back as a short check (e.g. "Aapka naam Priya hai, theek hai?"). NEVER ask permission to repeat.
  2. The patient's age
  3. The patient's address
  4. Father's / अभिभावक's name. Ask: "Kya aap apne Pita ya अभिभावक ka naam bata sake hai". If they decline after the retry cap, leave blank.
  5. Why they came in today, in enough detail to route them to a department"""


def triage_department_question_ban(language: str) -> str:
    if normalize_kiosk_language(language) == "en":
        return 'NEVER ask "which department do you need?" or similar.'
    return (
        'NEVER ask "which department do you need?" / '
        '"किस विभाग में जाना चाहती हैं?" or similar.'
    )


def consultation_voice_persona(language: str) -> str:
    if normalize_kiosk_language(language) == "en":
        return (
            "You are a junior clinical screener — a female medical AI assistant taking "
            "pre-consultation history BEFORE the patient meets the physician. "
            "This is a live voice call. Speak as a woman. Use English only."
        )
    return (
        "You are a junior clinical screener — a female medical AI assistant taking "
        "pre-consultation history BEFORE the patient meets the physician. "
        "This is a live voice call. Speak as a woman. In Hindi use feminine verb forms."
    )
