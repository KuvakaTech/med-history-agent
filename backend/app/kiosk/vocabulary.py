"""Guddi lesson vocabulary — word bank with image paths and ASR accept variants."""
from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Literal, Optional

LessonTopic = Literal[
    "Ghar", "Khana", "Jaanwar", "Rang", "Ginti", "Shareer", "Guddi-choose"
]
CardMode = Literal["teach", "quiz"]

_MANIFEST_PATH = (
    Path(__file__).resolve().parents[3]
    / "frontend"
    / "public"
    / "kiosk"
    / "vocabulary"
    / "manifest.json"
)


@lru_cache(maxsize=1)
def _image_extensions() -> dict[str, str]:
    """topic/word_id -> file extension from download manifest."""
    if not _MANIFEST_PATH.is_file():
        return {}
    data = json.loads(_MANIFEST_PATH.read_text(encoding="utf-8"))
    return {k: v if v.startswith(".") else f".{v}" for k, v in data.items()}


@dataclass(frozen=True)
class VocabWord:
    word_id: str
    topic: LessonTopic
    hindi: str
    accept: tuple[str, ...]
    image: str  # public URL path, e.g. /kiosk/vocabulary/khana/aam.jpg


def _image_path(topic: LessonTopic, word_id: str) -> str:
    key = f"{topic.lower()}/{word_id}"
    ext = _image_extensions().get(key, ".jpg")
    return f"/kiosk/vocabulary/{topic.lower()}/{word_id}{ext}"


def _entry(
    word_id: str,
    topic: LessonTopic,
    hindi: str,
    accept: list[str],
) -> VocabWord:
    return VocabWord(
        word_id=word_id,
        topic=topic,
        hindi=hindi,
        accept=tuple({word_id, hindi, *accept}),
        image=_image_path(topic, word_id),
    )


_VOCAB: dict[str, VocabWord] = {
    # Ghar
    "paani": _entry("paani", "Ghar", "पानी", ["pani", "paani", "water"]),
    "doodh": _entry("doodh", "Ghar", "दूध", ["dudh", "milk"]),
    "roti": _entry("roti", "Ghar", "रोटी", ["roti", "chapati"]),
    "ghar": _entry("ghar", "Ghar", "घर", ["ghar", "home", "house"]),
    "darwaza": _entry("darwaza", "Ghar", "दरवाज़ा", ["darwaza", "darwajaa", "door"]),
    "chulha": _entry("chulha", "Ghar", "चूल्हा", ["chulha", "chulhe", "stove"]),
    # Khana
    "daal": _entry("daal", "Khana", "दाल", ["dal", "daal", "lentils"]),
    "chawal": _entry("chawal", "Khana", "चावल", ["chawal", "rice", "chaval"]),
    "aam": _entry("aam", "Khana", "आम", ["aam", "am", "mango"]),
    "kela": _entry("kela", "Khana", "केला", ["kela", "banana"]),
    "sabzi": _entry("sabzi", "Khana", "सब्ज़ी", ["sabzi", "sabji", "vegetable"]),
    # Jaanwar
    "bakri": _entry("bakri", "Jaanwar", "बकरी", ["bakri", "goat"]),
    "gaay": _entry("gaay", "Jaanwar", "गाय", ["gay", "gaay", "cow", "gai"]),
    "kutta": _entry("kutta", "Jaanwar", "कुत्ता", ["kutta", "dog"]),
    "murgi": _entry("murgi", "Jaanwar", "मुर्गी", ["murgi", "murghi", "chicken"]),
    "chidiya": _entry("chidiya", "Jaanwar", "चिड़िया", ["chidiya", "bird"]),
    "bail": _entry("bail", "Jaanwar", "बैल", ["bail", "ox", "bull"]),
    # Rang
    "laal": _entry("laal", "Rang", "लाल", ["lal", "laal", "red"]),
    "peela": _entry("peela", "Rang", "पीला", ["pila", "peela", "yellow"]),
    "hara": _entry("hara", "Rang", "हरा", ["hara", "haara", "green"]),
    "neela": _entry("neela", "Rang", "नीला", ["nila", "neela", "blue"]),
    "safed": _entry("safed", "Rang", "सफ़ेद", ["safed", "safaid", "white"]),
    "kaala": _entry("kaala", "Rang", "काला", ["kala", "kaala", "black"]),
    # Ginti
    "ek": _entry("ek", "Ginti", "एक", ["ek", "one", "1"]),
    "do": _entry("do", "Ginti", "दो", ["do", "two", "2"]),
    "teen": _entry("teen", "Ginti", "तीन", ["teen", "tin", "three", "3"]),
    "chaar": _entry("chaar", "Ginti", "चार", ["char", "chaar", "four", "4"]),
    "paanch": _entry("paanch", "Ginti", "पाँच", ["panch", "paanch", "five", "5"]),
    "chhah": _entry("chhah", "Ginti", "छह", ["chhah", "chhe", "six", "6"]),
    # Shareer
    "aankh": _entry("aankh", "Shareer", "आँख", ["aankh", "ankh", "ank", "aank", "eye", "eyes"]),
    "kaan": _entry("kaan", "Shareer", "कान", ["kaan", "kan", "ear", "ears"]),
    "naak": _entry("naak", "Shareer", "नाक", ["naak", "nak", "nose"]),
    "haath": _entry("haath", "Shareer", "हाथ", ["hath", "haath", "hand"]),
    "pair": _entry("pair", "Shareer", "पैर", ["pair", "paer", "foot", "leg"]),
    "sir": _entry("sir", "Shareer", "सिर", ["sir", "head"]),
}

_TOPIC_WORDS: dict[str, list[str]] = {
    "Ghar": ["paani", "doodh", "roti", "ghar", "darwaza", "chulha"],
    "Khana": ["roti", "daal", "chawal", "aam", "kela", "sabzi"],
    "Jaanwar": ["bakri", "gaay", "kutta", "murgi", "chidiya", "bail"],
    "Rang": ["laal", "peela", "hara", "neela", "safed", "kaala"],
    "Ginti": ["ek", "do", "teen", "chaar", "paanch", "chhah"],
    "Shareer": ["aankh", "kaan", "naak", "haath", "pair", "sir"],
}


def get_word(word_id: str) -> Optional[VocabWord]:
    return _VOCAB.get((word_id or "").strip().lower())


def get_word_for_lesson(word_id: str, lesson_topic: str | None) -> Optional[VocabWord]:
    """Resolve word with image path for the active lesson topic."""
    base = get_word(word_id)
    if base is None:
        return None
    topic = (lesson_topic or "").strip()
    if topic and topic in _TOPIC_WORDS and word_id in _TOPIC_WORDS[topic]:
        topic_key = topic
    else:
        topic_key = base.topic
    return VocabWord(
        word_id=base.word_id,
        topic=topic_key,  # type: ignore[arg-type]
        hindi=base.hindi,
        accept=base.accept,
        image=_image_path(topic_key, word_id),
    )


def topic_cover_image(topic: str) -> str:
    """Representative cover image for topic picker on the start screen."""
    covers: dict[str, str] = {
        "Ghar": "ghar",
        "Khana": "aam",
        "Jaanwar": "bakri",
        "Rang": "laal",
        "Ginti": "ek",
        "Shareer": "aankh",
        "Guddi-choose": "guddi",
    }
    topic = (topic or "").strip()
    word_id = covers.get(topic, "guddi")
    if word_id == "guddi":
        return "/kiosk/vocabulary/topics/guddi.svg"
    folder = topic.lower() if topic != "Guddi-choose" else "ghar"
    if topic == "Rang":
        folder = "rang"
    elif topic == "Ginti":
        folder = "ginti"
    ext = _image_extensions().get(f"{folder}/{word_id}", ".jpg")
    return f"/kiosk/vocabulary/{folder}/{word_id}{ext}"


def first_word_for_topic(topic: str) -> Optional[str]:
    ids = _TOPIC_WORDS.get((topic or "").strip(), [])
    return ids[0] if ids else None


def words_for_topic(topic: str) -> list[VocabWord]:
    ids = _TOPIC_WORDS.get((topic or "").strip(), [])
    return [_VOCAB[w] for w in ids if w in _VOCAB]


def image_url(word_id: str) -> Optional[str]:
    w = get_word(word_id)
    return w.image if w else None


def all_word_ids() -> list[str]:
    return list(_VOCAB.keys())
