"""Roman/Hinglish captions → Devanagari for kiosk on-screen display."""
from __future__ import annotations

import re

from indic_transliteration import sanscript
from indic_transliteration.sanscript import transliterate

_DEVANAGARI_RE = re.compile(r"[\u0900-\u097F]")
_WORD_RE = re.compile(r"[A-Za-z']+")

# ASR often romanizes Hindi; map frequent words before ITRANS fallback.
_COMMON_ROMAN: dict[str, str] = {
    "aap": "आप",
    "aapka": "आपका",
    "aapki": "आपकी",
    "aapko": "आपको",
    "hai": "है",
    "hain": "हैं",
    "ho": "हो",
    "ji": "जी",
    "mein": "में",
    "main": "मैं",
    "yahan": "यहाँ",
    "ki": "की",
    "hoon": "हूँ",
    "karne": "करने",
    "namaste": "नमस्ते",
    "swaagat": "स्वागत",
    "shikayat": "शिकायत",
    "samasya": "समस्या",
    "madad": "मदद",
    "karungi": "करूँगी",
    "karunga": "करूँगा",
    "kripya": "कृपया",
    "batayein": "बताएँ",
    "batana": "बताना",
    "chahte": "चाहते",
    "chahenge": "चाहेंगे",
    "darj": "दर्ज",
    "kya": "क्या",
    "kaun": "कौन",
    "kaunsi": "कौनसी",
    "kahan": "कहाँ",
    "kab": "कब",
    "se": "से",
    "aur": "और",
    "yah": "यह",
    "yeh": "यह",
    "woh": "वह",
    "na": "ना",
    "nahi": "नहीं",
    "mat": "मत",
    "boliye": "बोलिए",
    "bol": "बोल",
    "sun": "सुन",
    "sunen": "सुनें",
    "jaankari": "जानकारी",
    "guptt": "गुप्त",
    "bank": "बैंक",
    "aadhaar": "आधार",
    "jan": "जन",
    "sunwai": "सुनवाई",
    "sahayak": "सहायक",
    "ai": "एआई",
}


def _is_mostly_devanagari(text: str) -> bool:
    letters = [c for c in text if c.isalpha()]
    if not letters:
        return False
    dev = sum(1 for c in letters if _DEVANAGARI_RE.match(c))
    return dev / len(letters) >= 0.4


def _roman_word_to_dev(word: str) -> str:
    low = word.lower()
    if low in _COMMON_ROMAN:
        return _COMMON_ROMAN[low]
    try:
        return transliterate(low, sanscript.ITRANS, sanscript.DEVANAGARI)
    except Exception:
        return word


def to_devanagari_display(text: str) -> str:
    """Show kiosk captions in Devanagari when ASR returns Latin Hindi."""
    if not text or not text.strip():
        return text
    if _is_mostly_devanagari(text):
        return text

    def replace_word(match: re.Match[str]) -> str:
        return _roman_word_to_dev(match.group(0))

    return _WORD_RE.sub(replace_word, text)
