"""Detect vocabulary words in Guddi's speech for auto-showing word cards."""
from __future__ import annotations

from typing import Literal, Optional

from app.kiosk.hindi_display import to_devanagari_display
from app.kiosk.vocabulary import VocabWord, _TOPIC_WORDS, _VOCAB, words_for_topic
from app.kiosk.word_text import normalize_text, text_contains_variant

CardMode = Literal["teach", "quiz"]

# Spoken / lesson phrases beyond the accept list (all Section 9 words)
_SPOKEN_ALIASES: dict[str, list[str]] = {
    # Ghar
    "paani": ["पानी", "pani", "paani", "water"],
    "doodh": ["दूध", "dudh", "milk"],
    "roti": ["रोटी", "roti", "chapati", "चपाती"],
    "ghar": ["घर", "ghar", "home", "house"],
    "darwaza": ["दरवाजा", "दरवाज़ा", "darwaza", "door"],
    "chulha": ["चूल्हा", "chulha", "stove", "chulhe"],
    # Khana
    "daal": ["दाल", "dal", "daal", "lentils"],
    "chawal": ["चावल", "chawal", "rice", "chaval"],
    "aam": ["आम", "aam", "mango"],
    "kela": ["केला", "kela", "banana"],
    "sabzi": ["सब्जी", "सब्ज़ी", "sabzi", "sabji", "vegetable"],
    # Jaanwar
    "bakri": ["बकरी", "bakri", "goat"],
    "gaay": ["गाय", "gay", "gaay", "cow", "gai"],
    "kutta": ["कुत्ता", "kutta", "dog"],
    "murgi": ["मुर्गी", "murgi", "murghi", "chicken"],
    "chidiya": ["चिड़िया", "chidiya", "bird"],
    "bail": ["बैल", "bail", "ox", "bull"],
    # Rang
    "laal": ["लाल", "lal", "laal", "red", "लाल रंग", "laal rang"],
    "peela": ["पीला", "pila", "peela", "yellow", "पीला रंग"],
    "hara": ["हरा", "hara", "green", "हरा रंग"],
    "neela": ["नीला", "nila", "neela", "blue", "नीला रंग"],
    "safed": ["सफेद", "सफ़ेद", "safed", "white", "सफेद रंग"],
    "kaala": ["काला", "kala", "kaala", "black", "काला रंग"],
    # Ginti
    "ek": ["एक", "ek", "one", "गिनती"],
    "do": ["दो", "do", "two"],
    "teen": ["तीन", "teen", "tin", "three"],
    "chaar": ["चार", "char", "chaar", "four"],
    "paanch": ["पाँच", "पांच", "panch", "paanch", "five"],
    "chhah": ["छह", "chhah", "chhe", "six"],
    # Shareer
    "aankh": ["आँख", "आंख", "aankh", "ankh", "ank", "aank", "eye"],
    "kaan": ["कान", "kaan", "kan", "ear"],
    "naak": ["नाक", "naak", "nak", "nose"],
    "haath": ["हाथ", "hath", "haath", "hand"],
    "pair": ["पैर", "pair", "foot", "leg"],
    "sir": ["सिर", "sir", "head"],
}


def _normalize(text: str) -> str:
    return normalize_text(text)


def _candidate_words(topic: str | None) -> list[VocabWord]:
    topic = (topic or "").strip()
    if topic and topic != "Guddi-choose":
        return words_for_topic(topic)
    seen: set[str] = set()
    out: list[VocabWord] = []
    for topic_name, ids in _TOPIC_WORDS.items():
        for wid in ids:
            if wid in seen:
                continue
            w = _VOCAB.get(wid)
            if w:
                seen.add(wid)
                out.append(w)
    return out


def detect_word_in_speech(
    text: str,
    topic: str | None,
) -> Optional[tuple[str, CardMode]]:
    """Return (word_id, mode) for the best vocabulary match in agent speech."""
    if not (text or "").strip():
        return None

    mode: CardMode = "teach"

    best: tuple[int, str] | None = None
    for word in _candidate_words(topic):
        variants: set[str] = set()
        for v in word.accept:
            n = _normalize(v)
            if n:
                variants.add(n)
            d = _normalize(to_devanagari_display(v))
            if d:
                variants.add(d)
        if word.hindi:
            variants.add(word.hindi)
            variants.add(_normalize(word.hindi))
        for alias in _SPOKEN_ALIASES.get(word.word_id, []):
            variants.add(alias)
            n = _normalize(alias)
            if n:
                variants.add(n)

        for variant in variants:
            if len(variant) < 2 and variant not in ("ek", "do"):
                continue
            if text_contains_variant(text, variant):
                score = len(variant)
                if best is None or score > best[0]:
                    best = (score, word.word_id)

    if best is None:
        return None
    return best[1], mode


def should_update_card(
    detected: tuple[str, CardMode],
    displayed_word_id: str | None,
    displayed_mode: str | None,
) -> bool:
    word_id, _mode = detected
    return displayed_word_id != word_id
