"""Heuristic validation for patient answers during clinical screening."""
from __future__ import annotations

import re

# STT placeholders and noise tokens that carry no clinical content.
_JUNK_PATTERNS = (
    r"^\[inaudible\]$",
    r"^\(silence\)$",
    r"^\[silence\]$",
    r"^\.+$",
    r"^\?+$",
    r"^-+$",
    r"^…+$",
)

_SKIP_PHRASES = (
    "i'd prefer to skip this question",
    "i would prefer to skip this question",
    "prefer to skip",
    "skip this question",
)


def is_skip_answer(text: str) -> bool:
    normalized = text.strip().lower().rstrip(".")
    return any(phrase in normalized for phrase in _SKIP_PHRASES)


def is_valid_answer(text: str) -> bool:
    """Return True when the answer is substantive enough to record and advance."""
    if is_skip_answer(text):
        return True

    stripped = text.strip()
    if not stripped:
        return False

    lowered = stripped.lower()
    for pattern in _JUNK_PATTERNS:
        if re.match(pattern, lowered, re.IGNORECASE):
            return False

    # Single digit or short numeric rating (e.g. severity "7" or "8/10").
    if re.fullmatch(r"\d{1,2}(/\d+)?", stripped):
        return True

    # Reject lone punctuation or single non-word character.
    if len(stripped) < 2:
        return False

    return True
