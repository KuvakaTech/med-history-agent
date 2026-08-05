"""Post-consultation diarization correction.

ElevenLabs Scribe v2 Realtime does not diarize (see plan §Research findings).
The batch Scribe v2 model does, up to 32 speakers. Once a cabin session ends,
run the archived audio through the batch model, cluster speakers, and correct
the stored utterance roles — the live LLM guesses become the permanent
record's starting point, and this pass tightens it.

Role names ("doctor"/"patient"/"attendee") are not something a diarizer knows —
it only knows "same speaker" clusters. We assign each cluster the role that the
live LLM attribution most often guessed for utterances in that cluster (majority
vote), then relabel every utterance in the cluster to match. This also gives us
an agreement-rate signal: how often the live LLM guess already matched the
diarizer's grouping — see the build-order verification step for how to use it.

Non-fatal by design: any failure here leaves `roles_verified=False` and the
live LLM roles stand as the record. Never call a provider SDK directly except
through this module's own httpx call — this is the one place in the app that
talks to ElevenLabs batch STT, mirroring the raw-httpx pattern already used in
app/agent/transcription/service.py and app/agent/tts/service.py.
"""

from __future__ import annotations

import logging
from collections import Counter
from typing import Optional

import httpx

from app.cabin.models import Utterance, UtteranceRole
from app.cabin.store import cabin_session_store
from app.core.config import settings
from app.storage import r2

log = logging.getLogger(__name__)

_BATCH_STT_URL = "https://api.elevenlabs.io/v1/speech-to-text"


class DiarizedSegment:
    __slots__ = ("speaker_id", "start", "end")

    def __init__(self, speaker_id: str, start: float, end: float) -> None:
        self.speaker_id = speaker_id
        self.start = start
        self.end = end


async def _run_batch_diarization(audio_bytes: bytes) -> list[DiarizedSegment]:
    async with httpx.AsyncClient(timeout=120) as client:
        response = await client.post(
            _BATCH_STT_URL,
            headers={"xi-api-key": settings.ELEVENLABS_API_KEY},
            data={"model_id": settings.ELEVENLABS_STT_BATCH_MODEL, "diarize": "true"},
            files={"file": ("audio.wav", audio_bytes, "audio/wav")},
        )
        response.raise_for_status()
        payload = response.json()

    segments: list[DiarizedSegment] = []
    for word in payload.get("words", []):
        speaker_id = word.get("speaker_id")
        start = word.get("start")
        end = word.get("end")
        if speaker_id is None or start is None or end is None:
            continue
        segments.append(
            DiarizedSegment(
                speaker_id=str(speaker_id), start=float(start), end=float(end)
            )
        )
    return segments


def _dominant_speaker(
    segments: list[DiarizedSegment], start: float, end: float
) -> Optional[str]:
    """Which diarized speaker cluster overlaps this utterance's time span the most."""
    overlap: Counter[str] = Counter()
    for seg in segments:
        overlap_secs = min(end, seg.end) - max(start, seg.start)
        if overlap_secs > 0:
            overlap[seg.speaker_id] += overlap_secs
    if not overlap:
        return None
    return overlap.most_common(1)[0][0]


def _match_utterances_to_clusters(
    utterances: list[Utterance], segments: list[DiarizedSegment]
) -> dict[str, str]:
    """utterance_id -> diarized speaker cluster, for utterances that carry timestamps
    and overlap a segment. Computed once and reused, since the overlap scan is the
    expensive part (segments are word-level, so there are thousands of them)."""
    matches: dict[str, str] = {}
    for utterance in utterances:
        if utterance.started_at is None or utterance.ended_at is None:
            continue
        cluster = _dominant_speaker(segments, utterance.started_at, utterance.ended_at)
        if cluster is not None:
            matches[utterance.utterance_id] = cluster
    return matches


def _assign_roles_by_majority_vote(
    utterances: list[Utterance], matches: dict[str, str]
) -> dict[str, UtteranceRole]:
    """Maps each diarized speaker cluster to the role the live LLM most often guessed
    for utterances in that cluster. The diarizer knows who spoke together, not who is
    the doctor — the LLM's guesses supply the role names, the clustering makes them
    consistent across every utterance by the same speaker."""
    cluster_votes: dict[str, Counter[UtteranceRole]] = {}
    for utterance in utterances:
        cluster = matches.get(utterance.utterance_id)
        if cluster is None:
            continue
        cluster_votes.setdefault(cluster, Counter())[utterance.role] += 1
    return {
        cluster: votes.most_common(1)[0][0] for cluster, votes in cluster_votes.items()
    }


async def rediarize(session_id: str) -> None:
    """Background task run after a cabin session ends. Non-fatal on any failure."""
    session = await cabin_session_store.get(session_id)
    if session is None:
        log.warning("rediarize: session %s not found", session_id)
        return
    if not session.audio_key:
        log.info("rediarize: session %s has no archived audio, skipping", session_id)
        return
    if not any(
        u.started_at is not None and u.ended_at is not None for u in session.utterances
    ):
        log.info(
            "rediarize: session %s has no utterance timestamps, skipping", session_id
        )
        return

    try:
        audio_bytes = await r2.download_audio(session.audio_key)
        segments = await _run_batch_diarization(audio_bytes)
    except Exception as exc:
        log.warning(
            "rediarize: batch diarization failed for session %s: %s", session_id, exc
        )
        return

    if not segments:
        log.warning(
            "rediarize: batch diarization returned no segments for session %s",
            session_id,
        )
        return

    matches = _match_utterances_to_clusters(session.utterances, segments)
    cluster_to_role = _assign_roles_by_majority_vote(session.utterances, matches)
    if not cluster_to_role:
        log.warning(
            "rediarize: no utterances could be matched to diarized segments for session %s",
            session_id,
        )
        return

    agreement = 0
    corrected = 0
    for utterance in session.utterances:
        cluster = matches.get(utterance.utterance_id)
        if cluster is None or cluster not in cluster_to_role:
            continue
        diarized_role = cluster_to_role[cluster]
        if diarized_role == utterance.role:
            agreement += 1
        else:
            corrected += 1
        utterance.role = diarized_role
        utterance.role_confidence = 0.9
        utterance.role_source = "diarizer"

    session.roles_verified = True
    await cabin_session_store.update(session)

    total = agreement + corrected
    log.info(
        "rediarize: session %s — %d utterances matched, %d corrected, agreement rate %.0f%%",
        session_id,
        total,
        corrected,
        (agreement / total * 100.0) if total else 0.0,
    )
