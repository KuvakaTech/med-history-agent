"""Match child speech against active vocabulary card."""
from __future__ import annotations

import re
from typing import Literal

from app.kiosk.hindi_display import to_devanagari_display
from app.kiosk.vocabulary import VocabWord, get_word
from app.kiosk.word_text import normalize_text, text_contains_variant

_DEVANAGARI_RE = re.compile(r"[\u0900-\u097F]")

MatchResult = Literal["clear", "close", "wrong"]

_GINTI_WORD_IDS = frozenset({"ek", "do", "teen", "chaar", "paanch", "chhah"})

# Known sound-alike wrong answers — checked before fuzzy match.
_WRONG_ANSWER_TOKENS: dict[str, frozenset[str]] = {
    "hara": frozenset({"heera", "hee ra", "हीरा", "हीर", "heere", "hira"}),
}


def _normalize(text: str) -> str:
    return normalize_text(text)


def _to_roman_tokens(text: str) -> list[str]:
    """Rough romanization for fuzzy compare — split on whitespace."""
    norm = _normalize(text)
    if not norm:
        return []
    dev = to_devanagari_display(norm)
    # Keep both original latin tokens and devanagari as single token
    parts = norm.split()
    if dev != norm:
        parts.append(_normalize(dev))
    return parts


def _levenshtein(a: str, b: str) -> int:
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        curr = [i]
        for j, cb in enumerate(b, 1):
            cost = 0 if ca == cb else 1
            curr.append(min(prev[j] + 1, curr[j - 1] + 1, prev[j - 1] + cost))
        prev = curr
    return prev[-1]


def _accept_variants(word: VocabWord) -> list[str]:
    variants: set[str] = set()
    for raw in word.accept:
        v = _normalize(raw)
        if v:
            variants.add(v)
        # ITRANS shortens roman vowels (hara→हर, heera→हीर) and causes false fuzzy matches.
        if _DEVANAGARI_RE.search(raw):
            dev = _normalize(to_devanagari_display(raw))
            if dev:
                variants.add(dev)
    return list(variants)


def match_answer(transcript: str, word_id: str) -> MatchResult:
    """Return clear, close, or wrong for child speech against word_id."""
    word = get_word(word_id)
    if not word:
        return "wrong"

    norm = _normalize(transcript)
    if not norm:
        return "wrong"

    variants = _accept_variants(word)
    dev_transcript = _normalize(to_devanagari_display(transcript))

    for v in variants:
        if text_contains_variant(transcript, v):
            return "clear"
        if text_contains_variant(dev_transcript, v):
            return "clear"

    # Ginti — numbers must not fuzzy-match each other (e.g. आठ ≠ पाँच).
    if word_id in _GINTI_WORD_IDS:
        return "wrong"

    reject = _WRONG_ANSWER_TOKENS.get(word_id)
    if reject:
        check = {norm, dev_transcript, *norm.split(), *dev_transcript.split()}
        if check & reject:
            return "wrong"

    tokens = norm.split() + dev_transcript.split()
    for token in tokens:
        if not token:
            continue
        for v in variants:
            dist = _levenshtein(token, v)
            # One edit max — catches haara≈hara but rejects heera≠hara.
            if dist <= 1:
                return "close" if dist > 0 else "clear"

    return "wrong"


def answer_hint(result: MatchResult, word: VocabWord, child_said: str) -> str:
    """Private system hint injected to Gemini after quiz answer."""
    hindi = word.hindi
    if result == "clear":
        return (
            f"[SYSTEM — private, do not read aloud] Child answered for card "
            f'"{word.word_id}" ({hindi}): said "{child_said}". CORRECT — celebrate warmly '
            f"and move on per feedback ladder."
        )
    if result == "close":
        return (
            f"[SYSTEM — private, do not read aloud] Child answered for card "
            f'"{word.word_id}" ({hindi}): said "{child_said}". CLOSE — say it together once: '
            f'"{hindi}", then cheer and move on. Max one more try, never harsh.'
        )
    return (
        f"[SYSTEM — private, do not read aloud] Child answered for card "
        f'"{word.word_id}" ({hindi}): said "{child_said}". INCORRECT — teach gently once '
        f'in Hindi only: "Yeh {hindi} hai. Ek baar saath mein bolo — {hindi}." '
        f"Never say galat. Never speak English or roman letters."
    )
