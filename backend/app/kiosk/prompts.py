"""Kiosk system prompt loader — centre kind selects voice agent context."""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from app.kiosk.models import KioskCentre, prompt_file_for_centre
from app.kiosk.vocabulary import words_for_topic

_PROMPTS_DIR = Path(__file__).resolve().parent / "prompts"
_V2_PROMPT_FILE = "jan_sunwai_v2_system.txt"


def _is_jan_sunwai_v2(centre: KioskCentre) -> bool:
    return prompt_file_for_centre(centre) == _V2_PROMPT_FILE


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


def _grievance_runtime(centre: KioskCentre, language: str) -> str:
    if _is_jan_sunwai_v2(centre):
        return (
            "\n\nAsk exactly ONE question per turn, then wait for the answer. "
            "Greet in Hindi first, then offer Hindi or English (section 2.1). "
            "After they choose, speak only in that language for the rest of the session. "
            "When speaking Hindi, use Devanagari script for everything you say aloud — it is shown live on the kiosk screen. "
            "When speaking English, use English on screen (do not transliterate). "
            "CRITICAL — COMPLAINT NUMBER: You do NOT know the complaint number during this call. "
            "NEVER invent, guess, or speak any complaint number "
            "(no JS-V2-, JS-VNS-, NN-VNS-, NNVNS-, or random digits). "
            "The system assigns the official number only after the citizen ends the call; "
            "it appears on the acknowledgement slip and at the counter. "
            "Never voice the ID — tell the citizen they can get it from the parchi or counter."
        )
    lang = _language_name(language)
    return (
        f"\n\nSpeak only in {lang}. "
        "Use Hindi (Devanagari script) for everything you say aloud — it is shown live on the kiosk screen. "
        "Ask exactly ONE question per turn, then wait for the answer. "
        "NEVER ask which language the citizen prefers (no Hindi/English choice). "
        "This kiosk is Hindi-only: greet in Hindi and ask what problem they want to register. "
        "CRITICAL — COMPLAINT NUMBER: You do NOT know the complaint number during this call. "
        "NEVER invent, guess, or speak any complaint number (no JS-VNS-, NN-VNS-, NNVNS-, or random digits). "
        "The system assigns the official number only after the citizen ends the call; "
        "it appears on the result screen (and slip/counter if available). "
        "Never voice the ID — tell the citizen they can get it from the screen, parchi, or counter."
    )


def system_instruction(
    centre: KioskCentre,
    language: str,
    phone_on_record: str | None = None,
) -> str:
    base = _load_base_prompt(centre)
    runtime = _grievance_runtime(centre, language)
    phone_note = ""
    if phone_on_record:
        phone_note = (
            f"\nPhone already captured at intake ({phone_on_record}) — "
            "do not ask the citizen to say their phone number aloud."
        )
    return base + runtime + phone_note


def system_instruction_learning(
    centre: KioskCentre,
    language: str,
    learner_name: Optional[str],
    lesson_topic: Optional[str],
) -> str:
    base = _load_base_prompt(centre)
    lang = _language_name(language)
    name_val = (learner_name or "").strip() or "-"
    topic_val = (lesson_topic or "").strip() or "Guddi-choose"
    topic_words = words_for_topic(topic_val) if topic_val != "Guddi-choose" else []
    word_ids = ", ".join(w.word_id for w in topic_words) if topic_words else "(choose from Section 9)"
    session_inputs = (
        f"\n\n--- SESSION INPUTS (Section 0 — use these, do not re-ask) ---\n"
        f"LESSON_TOPIC: {topic_val}\n"
        f"LEARNER_NAME: {name_val}\n"
        f"WORD_IDS_FOR_TOPIC: {word_ids}\n"
        f"(Call show_word_card with these word_id values only.)\n"
    )
    runtime = (
        f"\n\nSpeak only in {lang}. "
        "Use Hindi (Devanagari script) for everything you say aloud — it is shown live on the kiosk screen. "
        "Ask exactly ONE short thing per turn, then wait and listen. "
        "This is a children's Hindi learning session — never use test/exam language, never announce scores. "
        "Collect NO phone number, address, school name, or other personal data (optional first name only). "
        "When the lesson is complete (or the child wants to stop), call finish_lesson. "
        "Never read the learning record aloud to the child. "
        "For every word you teach or quiz, call show_word_card first — the kiosk also "
        "auto-shows the picture when you name a lesson word, but always call the tool "
        "before you speak about the object or colour. Never describe pointing or gestures. "
        "Speak ONLY in Devanagari Hindi aloud — never say roman spellings like kaan or aam. "
        "For quiz mode, call show_word_card with mode=quiz before asking the child to name it."
    )
    return base + session_inputs + runtime


def kickoff_text(centre: KioskCentre, language: str) -> str:
    if _is_jan_sunwai_v2(centre):
        return (
            f"The citizen is now at the kiosk for {centre.name}. "
            "Greet them warmly in Hindi first (section 2.1): disclose you are AI, "
            "offer Hindi or English, then invite them to register their problem. "
            "Do not wait for further instructions."
        )
    lang = _language_name(language)
    return (
        f"The citizen is now at the kiosk for {centre.name}. "
        f"Greet them warmly in {lang} only. "
        "Do NOT ask Hindi or English — begin intake immediately. "
        "Do not wait for further instructions."
    )


def kickoff_text_learning(
    centre: KioskCentre,
    language: str,
    learner_name: Optional[str],
    lesson_topic: Optional[str],
) -> str:
    lang = _language_name(language)
    name_part = ""
    if learner_name and learner_name.strip():
        name_part = f" The child's first name is {learner_name.strip()} — use it warmly."
    topic_part = ""
    if lesson_topic and lesson_topic.strip() and lesson_topic.strip() != "Guddi-choose":
        topic_part = f" Today's lesson topic is {lesson_topic.strip()}."
    return (
        f"A child is now at the Guddi learning kiosk for {centre.name}.{name_part}{topic_part} "
        f"Greet them as Guddi in {lang}, do a quick mood check, and begin the lesson playfully. "
        "Do not wait for further instructions."
    )
