"""Post-call learning record for the speech-only Guddi talk kiosk."""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from pydantic import BaseModel, Field

from app.agent import llm
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

_MOODS = {"happy", "tired", "shy", "excited", "unclear"}
_FLAGS = {"none", "needs-a-grown-up", "very-shy", "distress-noted"}


class GuddiTalkExtract(BaseModel):
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


_EXTRACT_PROMPT = """\
Extract a Guddi Hindi lesson record from this voice transcript.

Rules:
- Use ONLY what was clearly said. Do not invent words or dialect words.
- topic: the lesson topic Guddi actually taught (फल, जानवर, रंग, खाना, शरीर, or the Hindi name used).
- Each practiced word: clear (said well on their own), emerging (close or only with Guddi), not_yet (no try or still unclear).
- said_in_dialect: true only if the child used a home-language word for that idea.
- flags: none | needs-a-grown-up | very-shy | distress-noted.
- engagement: high | medium | low, with a short note in the same field.
- friendly_summary: one warm Hindi line for the Anganwadi worker, with one practice idea.
- Do not extract a child's name, age, address, school, or family details.

Transcript:
{transcript}
"""


def _duration_minutes(session: KioskSession) -> int:
    end = session.ended_at or datetime.utcnow()
    delta = end - session.started_at
    return max(1, int(delta.total_seconds() / 60))


async def run_guddi_talk_extract(
    session: KioskSession,
    centre: KioskCentre,
) -> KioskSession:
    if centre_kind_for(centre) != "talk":
        raise ValueError("run_guddi_talk_extract requires a talk centre")

    transcript_text = format_transcript(session.transcript)
    if not transcript_text.strip():
        session.status = "partial"
        session.phase = "result"
        session.ended_at = datetime.utcnow()
        await kiosk_session_store.update(session)
        return session

    extracted = GuddiTalkExtract()
    try:
        extracted = await llm.complete_structured(  # type: ignore[assignment]
            _EXTRACT_PROMPT.format(transcript=transcript_text),
            GuddiTalkExtract,
            fast=False,
            max_tokens=4096,
        )
    except Exception as exc:
        log.error(
            "Guddi talk extract failed for %s: %s",
            session.session_id,
            exc,
            exc_info=True,
        )

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    mood = extracted.mood_start if extracted.mood_start in _MOODS else None
    flags = extracted.flags if extracted.flags in _FLAGS else "none"
    session.learning_record = LearningRecord(
        date=today,
        duration_est=_duration_minutes(session),
        mood_start=mood,  # type: ignore[arg-type]
        topic=extracted.topic,
        words_practiced=extracted.words_practiced,
        new_words_clear=extracted.new_words_clear,
        emerging_words=extracted.emerging_words,
        pronunciation_note=extracted.pronunciation_note,
        dialect_bridges=extracted.dialect_bridges,
        milestone_signal=extracted.milestone_signal,
        engagement=extracted.engagement,
        flags=flags,  # type: ignore[arg-type]
        next_focus=extracted.next_focus,
        friendly_summary=extracted.friendly_summary,
    )
    session.lesson_topic = extracted.topic or session.lesson_topic
    session.status = "completed"
    session.phase = "result"
    session.ended_at = datetime.utcnow()
    await kiosk_session_store.update(session)
    return session
