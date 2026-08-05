"""Live gap alerts, and above all their gating.

An alert that fires on every 8s panel pass would be both expensive and useless — the
doctor would learn to ignore it. Most of these tests assert that the call did *not*
happen.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

from app.cabin.gaps import Gap, GapAlerts, gap_key
from app.cabin.models import AskedQuestion, ClinicalPanel
from app.clinical.patient import KnownCondition, Patient
from app.clinical.profile import PatientProfile, build_profile
from app.core.config import settings

from test_cabin_live import make_live, make_session, types_of


def a_profile() -> PatientProfile:
    return build_profile(
        Patient(
            doctor_id="doc-1",
            name="Asha",
            age=54,
            conditions=[KnownCondition(name="Type 2 diabetes")],
        ),
        [],
    )


def one_gap() -> GapAlerts:
    return GapAlerts(
        gaps=[
            Gap(
                condition="Type 2 diabetes",
                question="Ask about recent blood sugar readings.",
                rationale="Known T2DM; glycaemic control not discussed.",
            )
        ]
    )


def live_with_profile(monkeypatch, profile: PatientProfile | None = None):
    session = make_session()
    session.patient_id = "pat-1"
    live, ws = make_live(session)
    live._profile = profile if profile is not None else a_profile()
    live._profile_loaded = True
    return live, ws


# ── the gates ─────────────────────────────────────────────────────────────


async def test_no_patient_means_no_call_at_all():
    """A walk-in with no record is the common case and must cost nothing."""
    live, ws = make_live()  # session.patient_id is None
    with patch("app.cabin.live.detect_gaps", new=AsyncMock()) as detect:
        await live._maybe_emit_gaps(panel_changed=True)
    detect.assert_not_awaited()
    assert "gap_alert" not in types_of(ws)


async def test_an_empty_profile_disables_the_feature(monkeypatch):
    live, ws = make_live_with_empty_profile()
    with patch("app.cabin.live.detect_gaps", new=AsyncMock()) as detect:
        await live._maybe_emit_gaps(panel_changed=True)
    detect.assert_not_awaited()


def make_live_with_empty_profile():
    session = make_session()
    session.patient_id = "pat-1"
    live, ws = make_live(session)
    live._profile = PatientProfile()
    live._profile_loaded = True
    return live, ws


async def test_no_call_when_the_panel_did_not_clinically_change(monkeypatch):
    """Reuses the same signal that gates the expensive suggest call: if nothing new
    arrived clinically, nothing new can be a gap."""
    live, _ = live_with_profile(monkeypatch)
    with patch("app.cabin.live.detect_gaps", new=AsyncMock()) as detect:
        await live._maybe_emit_gaps(panel_changed=False)
    detect.assert_not_awaited()


async def test_the_minimum_interval_is_respected(monkeypatch):
    monkeypatch.setattr(settings, "CABIN_GAP_MIN_INTERVAL_SECS", 9999.0)
    live, _ = live_with_profile(monkeypatch)
    with patch(
        "app.cabin.live.detect_gaps", new=AsyncMock(return_value=one_gap())
    ) as detect:
        await live._maybe_emit_gaps(panel_changed=True)
        await live._maybe_emit_gaps(panel_changed=True)
    assert detect.await_count == 1, "fired twice inside the minimum interval"


async def test_the_per_session_pass_ceiling_holds(monkeypatch):
    """Bounds a pathological consultation regardless of how much the panel churns."""
    monkeypatch.setattr(settings, "CABIN_GAP_MIN_INTERVAL_SECS", 0.0)
    monkeypatch.setattr(settings, "CABIN_GAP_MAX_PASSES", 2)
    live, _ = live_with_profile(monkeypatch)

    with patch(
        "app.cabin.live.detect_gaps", new=AsyncMock(return_value=GapAlerts())
    ) as detect:
        for _ in range(6):
            await live._maybe_emit_gaps(panel_changed=True)
    assert detect.await_count == 2


# ── emission ──────────────────────────────────────────────────────────────


async def test_a_gap_is_emitted_once_and_never_repeated(monkeypatch):
    """The same 'ask about blood sugar' six times trains the doctor to ignore it."""
    monkeypatch.setattr(settings, "CABIN_GAP_MIN_INTERVAL_SECS", 0.0)
    live, ws = live_with_profile(monkeypatch)

    with patch("app.cabin.live.detect_gaps", new=AsyncMock(return_value=one_gap())):
        await live._maybe_emit_gaps(panel_changed=True)
        await live._maybe_emit_gaps(panel_changed=True)

    assert types_of(ws).count("gap_alert") == 1


async def test_no_frame_is_sent_when_there_are_no_gaps(monkeypatch):
    """An empty gaps array is noise; say nothing instead."""
    monkeypatch.setattr(settings, "CABIN_GAP_MIN_INTERVAL_SECS", 0.0)
    live, ws = live_with_profile(monkeypatch)
    with patch("app.cabin.live.detect_gaps", new=AsyncMock(return_value=GapAlerts())):
        await live._maybe_emit_gaps(panel_changed=True)
    assert "gap_alert" not in types_of(ws)


async def test_the_frame_carries_the_gap_shape(monkeypatch):
    monkeypatch.setattr(settings, "CABIN_GAP_MIN_INTERVAL_SECS", 0.0)
    live, ws = live_with_profile(monkeypatch)
    with patch("app.cabin.live.detect_gaps", new=AsyncMock(return_value=one_gap())):
        await live._maybe_emit_gaps(panel_changed=True)

    frame = next(m for m in ws.sent if m["type"] == "gap_alert")
    assert frame["gaps"][0]["condition"] == "Type 2 diabetes"
    assert "question" in frame["gaps"][0]
    assert "rationale" in frame["gaps"][0]
    assert "seq" in frame


async def test_a_failure_is_silent_and_harmless(monkeypatch):
    """A missing alert is not worth alarming the doctor about, and must never disturb
    the transcript."""
    monkeypatch.setattr(settings, "CABIN_GAP_MIN_INTERVAL_SECS", 0.0)
    live, ws = live_with_profile(monkeypatch)
    live._append_utterance("chest pain since morning")

    with patch(
        "app.cabin.live.detect_gaps", new=AsyncMock(side_effect=RuntimeError("down"))
    ):
        await live._maybe_emit_gaps(panel_changed=True)

    assert "gap_alert" not in types_of(ws)
    assert "error" not in types_of(ws)
    assert len(live.utterances) == 1


# ── input bounding ────────────────────────────────────────────────────────


async def test_detect_gaps_never_receives_the_transcript():
    """Cost must not scale with consultation length. The question is 'what has not been
    covered', which the asked-questions list answers without the transcript."""
    panel = ClinicalPanel(questions_asked=[AskedQuestion(text="Any chest pain?")])
    captured = {}

    async def fake_structured(prompt, schema, **kwargs):
        captured["prompt"] = prompt
        captured["fast"] = kwargs.get("fast")
        return GapAlerts()

    with patch("app.cabin.gaps.llm.complete_structured", new=fake_structured):
        from app.cabin.gaps import detect_gaps

        await detect_gaps(a_profile(), panel)

    assert "Any chest pain?" in captured["prompt"]
    assert "Type 2 diabetes" in captured["prompt"]
    assert captured["fast"] is True, "gap checks belong on the cheap tier"


def test_gap_key_normalises_for_dedupe():
    a = Gap(condition="Type 2 Diabetes", question="Ask  about sugar", rationale="x")
    b = Gap(condition="type 2 diabetes", question="ask about sugar", rationale="y")
    assert gap_key(a) == gap_key(b)
