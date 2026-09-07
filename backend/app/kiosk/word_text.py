"""Whole-word matching helpers for vocabulary detection."""
from __future__ import annotations

import re
import unicodedata

from app.kiosk.hindi_display import to_devanagari_display

_TOKEN_SPLIT = re.compile(r"[\s,—\-!?।;:()]+")
_DEVANAGARI_RE = re.compile(r"[\u0900-\u097F]")


def normalize_text(text: str) -> str:
    text = unicodedata.normalize("NFC", (text or "").strip().lower())
    text = re.sub(r"[^\w\s\u0900-\u097F]", " ", text, flags=re.UNICODE)
    return re.sub(r"\s+", " ", text).strip()


def _tokenize(text: str) -> set[str]:
    tokens: set[str] = set()
    for raw in _TOKEN_SPLIT.split(text or ""):
        piece = raw.strip()
        if not piece:
            continue
        tokens.add(piece)
        norm = normalize_text(piece)
        if norm:
            tokens.add(norm)
        dev = normalize_text(to_devanagari_display(piece))
        if dev:
            tokens.add(dev)
    return tokens


def text_contains_variant(text: str, variant: str) -> bool:
    """Match vocabulary variants as whole words — avoids दो inside दोस्त."""
    if not (text or "").strip() or not (variant or "").strip():
        return False

    variant = variant.strip()
    norm = normalize_text(text)
    dev = normalize_text(to_devanagari_display(text))
    tokens = _tokenize(text) | _tokenize(norm) | _tokenize(dev)

    # Multi-word phrases (e.g. "laal rang") — phrase match only.
    if " " in variant:
        v_norm = normalize_text(variant)
        return variant in text or (v_norm and v_norm in norm) or (v_norm and v_norm in dev)

    v_norm = normalize_text(variant)
    candidates = {variant, v_norm}
    if _DEVANAGARI_RE.search(variant):
        candidates.add(variant)

    for cand in candidates:
        if not cand:
            continue
        if cand in tokens:
            return True
        # Longer variants may appear with light punctuation attached to one token.
        if len(cand) >= 5:
            for tok in tokens:
                if tok == cand or tok.startswith(cand) or tok.endswith(cand):
                    if abs(len(tok) - len(cand)) <= 1:
                        return True
    return False
