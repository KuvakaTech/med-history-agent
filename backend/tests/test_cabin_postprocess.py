"""Post-consultation diarization tests.

Scribe v2 Realtime does not diarize, so live roles are LLM guesses. The batch model
does, and this pass reconciles the two: the diarizer supplies the speaker grouping,
the LLM guesses supply the role names, and a majority vote per cluster makes the
labels consistent across every utterance by the same speaker.
"""

from __future__ import annotations

from datetime import datetime
from unittest.mock import AsyncMock, patch

import pytest

from app.cabin.models import CabinSession, Utterance, UtteranceRole
from app.cabin.postprocess import (
    DiarizedSegment,
    _assign_roles_by_majority_vote,
    _dominant_speaker,
    _match_utterances_to_clusters,
    rediarize,
)
from app.cabin.store import cabin_session_store
from app.clinical.context import Specialty


def utt(
    uid: str, role: UtteranceRole, start: float | None, end: float | None, seq: int = 0
) -> Utterance:
    return Utterance(
        utterance_id=uid,
        seq=seq,
        text=f"text-{uid}",
        role=role,
        started_at=start,
        ended_at=end,
    )


# ── overlap matching ──────────────────────────────────────────────────────


def test_dominant_speaker_picks_the_largest_overlap():
    segments = [DiarizedSegment("spk_0", 0.0, 3.0), DiarizedSegment("spk_1", 3.0, 10.0)]
    # 2.5-9.0 overlaps spk_0 by 0.5s and spk_1 by 6.0s
    assert _dominant_speaker(segments, 2.5, 9.0) == "spk_1"


def test_dominant_speaker_returns_none_when_no_overlap():
    segments = [DiarizedSegment("spk_0", 0.0, 3.0)]
    assert _dominant_speaker(segments, 50.0, 60.0) is None


def test_utterances_without_timestamps_are_skipped():
    segments = [DiarizedSegment("spk_0", 0.0, 5.0)]
    utterances = [
        utt("a", UtteranceRole.DOCTOR, None, None),
        utt("b", UtteranceRole.PATIENT, 1.0, 2.0),
    ]
    matches = _match_utterances_to_clusters(utterances, segments)
    assert matches == {"b": "spk_0"}


# ── majority vote ─────────────────────────────────────────────────────────


def test_majority_vote_corrects_a_minority_misguess():
    """The whole point: one utterance the LLM got wrong is outvoted by the rest of
    that speaker's cluster."""
    segments = [
        DiarizedSegment("spk_0", 0.0, 10.0),
        DiarizedSegment("spk_1", 10.0, 20.0),
    ]
    utterances = [
        utt("a", UtteranceRole.DOCTOR, 0.0, 3.0, 0),
        utt("b", UtteranceRole.DOCTOR, 3.0, 6.0, 1),
        utt("c", UtteranceRole.PATIENT, 6.0, 9.0, 2),  # same speaker, mislabelled
        utt("d", UtteranceRole.PATIENT, 11.0, 15.0, 3),
    ]
    matches = _match_utterances_to_clusters(utterances, segments)
    roles = _assign_roles_by_majority_vote(utterances, matches)

    assert (
        roles["spk_0"] == UtteranceRole.DOCTOR
    ), "minority guess should have been outvoted"
    assert roles["spk_1"] == UtteranceRole.PATIENT


def test_three_speaker_cabin_maps_all_roles():
    segments = [
        DiarizedSegment("spk_0", 0.0, 5.0),
        DiarizedSegment("spk_1", 5.0, 10.0),
        DiarizedSegment("spk_2", 10.0, 15.0),
    ]
    utterances = [
        utt("a", UtteranceRole.DOCTOR, 0.0, 4.0, 0),
        utt("b", UtteranceRole.PATIENT, 5.5, 9.0, 1),
        utt("c", UtteranceRole.ATTENDEE, 10.5, 14.0, 2),
    ]
    roles = _assign_roles_by_majority_vote(
        utterances, _match_utterances_to_clusters(utterances, segments)
    )
    assert set(roles.values()) == {
        UtteranceRole.DOCTOR,
        UtteranceRole.PATIENT,
        UtteranceRole.ATTENDEE,
    }


# ── the rediarize pass end to end ─────────────────────────────────────────


async def _seed(**overrides) -> CabinSession:
    session = CabinSession(
        session_id="sess-rd",
        doctor_id="doc-1",
        specialty=Specialty.GENERAL_MEDICINE,
        consent_captured_at=datetime.utcnow(),
        status="ended",
        **overrides,
    )
    await cabin_session_store.create(session)
    return session


@pytest.mark.asyncio
async def test_rediarize_corrects_roles_and_marks_verified():
    await _seed(
        audio_key="audio/sess-rd/a.wav",
        utterances=[
            utt("a", UtteranceRole.DOCTOR, 0.0, 3.0, 0),
            utt(
                "b", UtteranceRole.PATIENT, 3.0, 6.0, 1
            ),  # same cluster as 'a' — should flip
            utt("c", UtteranceRole.PATIENT, 11.0, 15.0, 2),
        ],
    )
    segments = [
        DiarizedSegment("spk_0", 0.0, 10.0),
        DiarizedSegment("spk_1", 10.0, 20.0),
    ]

    with (
        patch(
            "app.cabin.postprocess.r2.download_audio",
            new=AsyncMock(return_value=b"fake-wav"),
        ),
        patch(
            "app.cabin.postprocess._run_batch_diarization",
            new=AsyncMock(return_value=segments),
        ),
    ):
        await rediarize("sess-rd")

    updated = await cabin_session_store.get("sess-rd")
    assert updated.roles_verified is True
    assert updated.utterances[1].role == UtteranceRole.DOCTOR, "misguess not corrected"
    assert updated.utterances[1].role_source == "diarizer"
    assert updated.utterances[2].role == UtteranceRole.PATIENT


@pytest.mark.asyncio
async def test_rediarize_is_non_fatal_when_diarization_fails():
    """A failed pass must leave the LLM roles standing, not corrupt the record."""
    await _seed(
        audio_key="audio/sess-rd/a.wav",
        utterances=[utt("a", UtteranceRole.DOCTOR, 0.0, 3.0, 0)],
    )
    with (
        patch(
            "app.cabin.postprocess.r2.download_audio", new=AsyncMock(return_value=b"x")
        ),
        patch(
            "app.cabin.postprocess._run_batch_diarization",
            new=AsyncMock(side_effect=RuntimeError("api down")),
        ),
    ):
        await rediarize("sess-rd")

    updated = await cabin_session_store.get("sess-rd")
    assert updated.roles_verified is False
    assert updated.utterances[0].role == UtteranceRole.DOCTOR


@pytest.mark.asyncio
async def test_rediarize_skips_when_no_audio_or_no_timestamps():
    await _seed(
        utterances=[utt("a", UtteranceRole.DOCTOR, 0.0, 3.0, 0)]
    )  # no audio_key
    with patch("app.cabin.postprocess._run_batch_diarization", new=AsyncMock()) as mock:
        await rediarize("sess-rd")
    mock.assert_not_awaited()

    cabin_session_store  # noqa: B018  (store cleared by the autouse fixture between tests)
    await _seed(
        audio_key="k", utterances=[utt("a", UtteranceRole.DOCTOR, None, None, 0)]
    )
    with patch("app.cabin.postprocess._run_batch_diarization", new=AsyncMock()) as mock:
        await rediarize("sess-rd")
    mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_rediarize_handles_missing_session():
    with patch("app.cabin.postprocess._run_batch_diarization", new=AsyncMock()) as mock:
        await rediarize("no-such-session")
    mock.assert_not_awaited()
