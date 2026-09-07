"""Post-call learning record extraction for Guddi kiosk centres."""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from pydantic import BaseModel, Field

from app.agent import llm
from app.kiosk.learning_engine import LearningEngine
from app.kiosk.models import (
    DialectBridge,
    KioskCentre,
    KioskSession,
    LearningRecord,
    WordPracticeResult,
    centre_kind_for,
)
from app.kiosk.post_call_extract import format_transcript
from app.kiosk.session_store import kiosk_session_store

log = logging.getLogger(__name__)


class LearningExtract(BaseModel):
    learner_name: Optional[str] = None
    mode_used: Optional[str] = None
    mood_start: Optional[str] = None
    topic: Optional[str] = None
    words_practiced: list[WordPracticeResult] = Field(default_factory=list)
    new_words_clear: Optional[int] = None
    emerging_words: Optional[int] = None
    pronunciation_note: Optional[str] = None
    dialect_bridges: list[DialectBridge] = Field(default_factory=list)
    milestone_signal: Optional[str] = None
    engagement: Optional[str] = None
    flags: Optional[str] = "none"
    next_focus: list[str] = Field(default_factory=list)
    friendly_summary: Optional[str] = None


_GUDDI_EXTRACT_PROMPT = """\
Extract a structured Guddi learning session record from this kiosk voice transcript.

Rules:
- Use ONLY what is explicitly said or clearly demonstrated. Do not invent facts or dialect words.
- Assess each practiced word as: clear (said well on own), emerging (needed help or close), not_yet (no attempt or unclear after ~2 tries).
- said_in_dialect: true if the child used their home dialect word for that concept.
- flags: none | needs-a-grown-up | very-shy | distress-noted (only if transcript shows distress/harm/scared/hungry/unsafe).
- Never extract phone, address, school, Aadhaar, or family details.
- engagement: high | medium | low with a short note in the engagement field text.
- friendly_summary: one warm line in Hindi+English for the teacher/parent.

Transcript:
{transcript}
"""


def _duration_minutes(session: KioskSession) -> int:
    end = session.ended_at or datetime.utcnow()
    delta = end - session.started_at
    return max(1, int(delta.total_seconds() / 60))


def _engine_words_from_snapshot(session: KioskSession) -> tuple[list[WordPracticeResult], int, int]:
    """Ground-truth word progress from lesson engine snapshot."""
    if not session.lesson_state:
        return [], 0, 0
    engine = LearningEngine.from_snapshot(session.lesson_state)
    practiced = engine.words_practiced_results()
    clear_n = sum(1 for w in practiced if w.result == "clear")
    emerging_n = sum(1 for w in practiced if w.result == "emerging")
    return practiced, clear_n, emerging_n


async def run_learning_extract(
    session: KioskSession,
    centre: KioskCentre,
) -> KioskSession:
    if centre_kind_for(centre) != "learning":
        raise ValueError("run_learning_extract requires a learning centre")

    transcript_text = format_transcript(session.transcript)
    if not transcript_text.strip():
        session.status = "partial"
        session.phase = "result"
        session.ended_at = datetime.utcnow()
        await kiosk_session_store.update(session)
        return session

    extracted = LearningExtract()
    try:
        extracted = await llm.complete_structured(  # type: ignore[assignment]
            _GUDDI_EXTRACT_PROMPT.format(transcript=transcript_text),
            LearningExtract,
            fast=False,
            max_tokens=4096,
        )
    except Exception as exc:
        log.error(
            "Kiosk learning extract failed for %s: %s",
            session.session_id,
            exc,
            exc_info=True,
        )

    learner = extracted.learner_name or session.learner_name
    topic = extracted.topic or session.lesson_topic
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    engine_words, engine_clear, engine_emerging = _engine_words_from_snapshot(session)
    words_practiced = engine_words if engine_words else extracted.words_practiced
    new_words_clear = engine_clear if engine_words else extracted.new_words_clear
    emerging_words = engine_emerging if engine_words else extracted.emerging_words

    session.learning_record = LearningRecord(
        learner_name=learner,
        date=today,
        duration_est=_duration_minutes(session),
        mode_used=extracted.mode_used,  # type: ignore[arg-type]
        mood_start=extracted.mood_start,  # type: ignore[arg-type]
        topic=topic,
        words_practiced=words_practiced,
        new_words_clear=new_words_clear,
        emerging_words=emerging_words,
        pronunciation_note=extracted.pronunciation_note,
        dialect_bridges=extracted.dialect_bridges,
        milestone_signal=extracted.milestone_signal,
        engagement=extracted.engagement,
        flags=extracted.flags or "none",  # type: ignore[arg-type]
        next_focus=extracted.next_focus,
        friendly_summary=extracted.friendly_summary,
    )
    session.status = "completed"
    session.phase = "result"
    session.ended_at = datetime.utcnow()
    await kiosk_session_store.update(session)
    return session
