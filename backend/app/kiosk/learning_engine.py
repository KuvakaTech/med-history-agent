"""Server-owned lesson flow for Guddi Learning kiosk."""
from __future__ import annotations

from typing import Any, Literal, Optional

from app.kiosk.models import WordPracticeResult
from app.kiosk.vocabulary import get_word, words_for_topic

LessonPhase = Literal["intro", "warmup", "teach", "recall", "close"]

MIN_WORDS_TO_FINISH = 4
DEFAULT_WORD_COUNT = 5
MAX_ATTEMPTS_PER_WORD = 2
MAX_RECALL_WORDS = 2

_INVITE_PHRASES = (
    "बोलो",
    "bolo",
    "साथ में",
    "saath mein",
    "तुम बोलो",
    "ab tum",
    "ek baar bolo",
    "एक बार बोलो",
)


def agent_invites_repeat(text: str) -> bool:
    """True when Guddi asks the child to repeat the word."""
    t = (text or "").lower()
    return any(p in t for p in _INVITE_PHRASES)


def _recall_word_ids(taught_words: list[str]) -> list[str]:
    """Pick up to 2 earlier words for recall (first and middle)."""
    if not taught_words:
        return []
    if len(taught_words) == 1:
        return [taught_words[0]]
    mid = len(taught_words) // 2
    return [taught_words[0], taught_words[mid]][:MAX_RECALL_WORDS]


class LearningEngine:
    """Tracks word order, progress, and whether finish_lesson is allowed."""

    def __init__(self, topic: str | None) -> None:
        self.phase: LessonPhase = "intro"
        self.topic = (topic or "").strip()
        self.word_queue: list[str] = []
        self.current_index: int = -1
        self.word_attempts: int = 0
        self.taught_words: list[str] = []
        self.word_progress: dict[str, str] = {}
        self.recall_queue: list[str] = []
        self.recall_index: int = -1
        self._build_queue()

    def _build_queue(self) -> None:
        if self.topic and self.topic != "Guddi-choose":
            ids = [w.word_id for w in words_for_topic(self.topic)]
            self.word_queue = ids[:DEFAULT_WORD_COUNT]

    def on_intro_complete(self) -> None:
        """Call after the child answers the mood check (turn_count >= 1)."""
        if self.phase != "intro":
            return
        self.phase = "warmup"
        self.current_index = 0
        self.word_attempts = 0

    def current_word_id(self) -> Optional[str]:
        if 0 <= self.current_index < len(self.word_queue):
            return self.word_queue[self.current_index]
        return None

    def start_recall(self) -> None:
        if self.phase != "recall":
            return
        if not self.recall_queue:
            self.recall_queue = _recall_word_ids(self.taught_words)
        self.recall_index = 0 if self.recall_queue else -1

    def current_recall_word(self) -> Optional[str]:
        if self.phase != "recall" or self.recall_index < 0:
            return None
        if self.recall_index >= len(self.recall_queue):
            return None
        return self.recall_queue[self.recall_index]

    def advance_recall(self) -> None:
        self.recall_index += 1
        self.word_attempts = 0
        if self.recall_index >= len(self.recall_queue):
            self.phase = "close"

    def expected_word_id(self) -> Optional[str]:
        """Word the kiosk should show right now."""
        if self.phase in ("intro", "close"):
            return None
        if self.phase == "recall":
            if self.recall_index < 0:
                return None
            return self.current_recall_word()
        return self.current_word_id()

    def expected_card_mode(self) -> str:
        return "quiz" if self.phase == "recall" else "teach"

    def can_finish_lesson(self) -> bool:
        return len(self.taught_words) >= MIN_WORDS_TO_FINISH or self.phase == "close"

    def record_answer(self, word_id: str, result: str) -> bool:
        """Record attempt; return True when this word is done (max tries or correct)."""
        self.word_attempts += 1
        if result in ("clear", "close"):
            self.word_progress[word_id] = "clear" if result == "clear" else "emerging"
            if word_id not in self.taught_words:
                self.taught_words.append(word_id)
            return True
        if self.word_attempts >= MAX_ATTEMPTS_PER_WORD:
            self.word_progress[word_id] = "not_yet"
            if word_id not in self.taught_words:
                self.taught_words.append(word_id)
            return True
        return False

    def advance_word(self) -> None:
        self.word_attempts = 0
        self.current_index += 1
        if self.current_index >= len(self.word_queue):
            self.phase = "recall"
            self.start_recall()
        elif self.phase == "warmup":
            self.phase = "teach"

    def sync_to_word(self, word_id: str) -> bool:
        """Jump engine to a queue word (when Guddi moves on in speech). No rewind."""
        if self.phase in ("intro", "close", "recall"):
            return False
        if word_id not in self.word_queue:
            return False
        idx = self.word_queue.index(word_id)
        if idx < self.current_index:
            return False
        for i in range(self.current_index, idx):
            skipped = self.word_queue[i]
            if skipped not in self.word_progress:
                self.word_progress[skipped] = "not_yet"
            if skipped not in self.taught_words:
                self.taught_words.append(skipped)
        self.current_index = idx
        self.word_attempts = 0
        if self.phase == "warmup" and idx > 0:
            self.phase = "teach"
        return True

    def validate_show_word_card(self, word_id: str, mode: str) -> Optional[str]:
        """Return error message if tool call disagrees with engine state."""
        if self.phase == "intro":
            return None
        if self.phase == "recall":
            expected = self.current_recall_word()
            if expected is None:
                return None
            if word_id != expected:
                return f"expected recall word_id={expected}, got {word_id}"
            if mode != "quiz":
                return f"expected mode=quiz for recall, got {mode}"
            return None
        if word_id not in self.word_queue:
            return f"word_id {word_id} not in lesson queue"
        idx = self.word_queue.index(word_id)
        if idx < self.current_index:
            return f"cannot show earlier word {word_id}"
        if mode != "teach":
            return f"expected mode=teach during lesson, got {mode}"
        return None

    def next_word_private_hint(self) -> Optional[str]:
        if self.phase == "recall":
            wid = self.current_recall_word()
            if wid:
                return (
                    f'[SYSTEM — private, do not read aloud] Recall quiz word: "{wid}". '
                    f'Call show_word_card(word_id="{wid}", mode=quiz). '
                    f"Ask child to name the picture."
                )
            if self.phase == "close":
                return (
                    "[SYSTEM — private, do not read aloud] Recall complete. "
                    "Celebrate and close the lesson when ready."
                )
            return (
                "[SYSTEM — private, do not read aloud] All words taught. "
                "Do Step 5 recall playfully, then close when ready."
            )
        wid = self.current_word_id()
        if not wid:
            return None
        return (
            f'[SYSTEM — private, do not read aloud] Next lesson word: "{wid}". '
            f'Call show_word_card(word_id="{wid}", mode=teach) BEFORE naming it. '
            f"Then invite the child to repeat. Do not skip ahead."
        )

    def finish_rejected_hint(self) -> str:
        need = max(0, MIN_WORDS_TO_FINISH - len(self.taught_words))
        return (
            f"[SYSTEM — private, do not read aloud] finish_lesson rejected — "
            f"only {len(self.taught_words)} words done, need at least {MIN_WORDS_TO_FINISH}. "
            f"Teach {need} more word(s) before closing."
        )

    def words_practiced_results(self) -> list[WordPracticeResult]:
        out: list[WordPracticeResult] = []
        for word_id, result in self.word_progress.items():
            word = get_word(word_id)
            label = word.hindi if word else word_id
            out.append(
                WordPracticeResult(
                    word=label,
                    result=result,  # type: ignore[arg-type]
                    said_in_dialect=False,
                )
            )
        return out

    def to_snapshot(self) -> dict[str, Any]:
        return {
            "phase": self.phase,
            "topic": self.topic,
            "word_queue": list(self.word_queue),
            "current_index": self.current_index,
            "word_attempts": self.word_attempts,
            "taught_words": list(self.taught_words),
            "word_progress": dict(self.word_progress),
            "recall_queue": list(self.recall_queue),
            "recall_index": self.recall_index,
        }

    @classmethod
    def from_snapshot(cls, data: dict[str, Any]) -> LearningEngine:
        engine = cls(data.get("topic"))
        engine.phase = data.get("phase", "intro")
        engine.word_queue = list(data.get("word_queue") or [])
        engine.current_index = int(data.get("current_index", -1))
        engine.word_attempts = int(data.get("word_attempts", 0))
        engine.taught_words = list(data.get("taught_words") or [])
        engine.word_progress = dict(data.get("word_progress") or {})
        engine.recall_queue = list(data.get("recall_queue") or [])
        engine.recall_index = int(data.get("recall_index", -1))
        return engine
