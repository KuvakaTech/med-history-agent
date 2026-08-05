"""Analysis-layer tests: the delta merge, the Sonnet gate, and bounded call inputs.

The bounding tests are the load-bearing ones. If any call's input or output starts
scaling with the length of the consultation, per-consult cost grows quadratically with
session length and nothing fails — it just gets expensive silently.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from app.cabin import analysis
from app.cabin.models import (
    AskedQuestion,
    ClinicalPanel,
    DiscussedMedication,
    LiveSuggestions,
    OrderedTest,
    PanelDelta,
    ReportedSymptom,
    RoleAttribution,
    Utterance,
    UtteranceRole,
)
from app.clinical.context import DifferentialDiagnosis
from app.core.config import settings


def _utt(
    text: str, role: UtteranceRole = UtteranceRole.PATIENT, seq: int = 0
) -> Utterance:
    return Utterance(utterance_id=f"u{seq}", seq=seq, text=text, role=role)


# ── the gate that decides whether Sonnet runs ─────────────────────────────


def test_empty_delta_does_not_trigger_suggestions():
    assert PanelDelta().has_clinical_change() is False


@pytest.mark.parametrize(
    "delta",
    [
        PanelDelta(new_symptoms=[ReportedSymptom(name="cough")]),
        PanelDelta(
            new_diagnoses=[
                DifferentialDiagnosis(
                    condition="dengue", likelihood="Medium", reasoning="r"
                )
            ]
        ),
        PanelDelta(new_tests=[OrderedTest(name="CBC", status="ordered")]),
        PanelDelta(
            new_medications=[
                DiscussedMedication(drug_name="metformin", action="discussed")
            ]
        ),
    ],
)
def test_new_clinical_content_triggers_suggestions(delta):
    assert delta.has_clinical_change() is True


def test_questions_alone_do_not_trigger_suggestions():
    """The doctor asking things churns every pass. If it fired the Sonnet call the
    gate would be doing nothing."""
    delta = PanelDelta(new_questions_asked=[AskedQuestion(text="when did it start?")])
    assert delta.has_clinical_change() is False


# ── merging deltas into the panel ─────────────────────────────────────────


def test_merge_appends_new_entries_to_an_empty_panel():
    delta = PanelDelta(
        new_symptoms=[ReportedSymptom(name="fever")],
        new_questions_asked=[AskedQuestion(text="onset")],
    )
    panel = analysis.merge_panel_delta(None, delta)
    assert [s.name for s in panel.symptoms] == ["fever"]
    assert [q.text for q in panel.questions_asked] == ["onset"]


def test_merge_deduplicates_case_insensitively():
    panel = ClinicalPanel(symptoms=[ReportedSymptom(name="fever")])
    merged = analysis.merge_panel_delta(
        panel, PanelDelta(new_symptoms=[ReportedSymptom(name="  Fever  ")])
    )
    assert len(merged.symptoms) == 1, "same symptom listed twice"


def test_merge_fills_in_a_detail_learned_later():
    """'Metformin' now, '500mg twice daily' three minutes later — the dose has to land
    on the existing entry rather than creating a second one."""
    panel = ClinicalPanel(
        medications=[DiscussedMedication(drug_name="metformin", action="discussed")]
    )
    merged = analysis.merge_panel_delta(
        panel,
        PanelDelta(
            new_medications=[
                DiscussedMedication(
                    drug_name="metformin",
                    dose="500mg",
                    frequency="twice daily",
                    action="started",
                )
            ]
        ),
    )
    assert len(merged.medications) == 1
    assert merged.medications[0].dose == "500mg"
    assert merged.medications[0].frequency == "twice daily"
    assert merged.medications[0].action == "started", "state field should advance"


def test_merge_does_not_erase_known_detail_with_a_vaguer_mention():
    """A later mention that says nothing new must not blank out what we already know."""
    panel = ClinicalPanel(
        symptoms=[ReportedSymptom(name="fever", detail="3 days, high grade")]
    )
    merged = analysis.merge_panel_delta(
        panel, PanelDelta(new_symptoms=[ReportedSymptom(name="fever")])
    )
    assert merged.symptoms[0].detail == "3 days, high grade"


def test_merge_applies_a_patient_self_correction():
    """'Teen din' then 'nahi, teen hafte' — keeping the first answer would leave a
    wrong duration on screen, and duration drives the differential."""
    panel = ClinicalPanel(symptoms=[ReportedSymptom(name="fever", detail="3 days")])
    merged = analysis.merge_panel_delta(
        panel,
        PanelDelta(new_symptoms=[ReportedSymptom(name="fever", detail="3 weeks")]),
    )
    assert merged.symptoms[0].detail == "3 weeks", "self-correction was discarded"


def test_merge_updates_a_dose_that_was_revised():
    panel = ClinicalPanel(
        medications=[
            DiscussedMedication(drug_name="metformin", dose="500mg", action="started")
        ]
    )
    merged = analysis.merge_panel_delta(
        panel,
        PanelDelta(
            new_medications=[
                DiscussedMedication(drug_name="metformin", dose="1g", action="started")
            ]
        ),
    )
    assert merged.medications[0].dose == "1g", "revised dose was discarded"


def test_merge_advances_test_status():
    panel = ClinicalPanel(tests=[OrderedTest(name="CBC", status="considered")])
    merged = analysis.merge_panel_delta(
        panel, PanelDelta(new_tests=[OrderedTest(name="CBC", status="ordered")])
    )
    assert len(merged.tests) == 1
    assert merged.tests[0].status == "ordered"


def test_merge_does_not_mutate_the_input_panel():
    panel = ClinicalPanel(symptoms=[ReportedSymptom(name="fever")])
    analysis.merge_panel_delta(
        panel, PanelDelta(new_symptoms=[ReportedSymptom(name="cough")])
    )
    assert [s.name for s in panel.symptoms] == ["fever"], "merge mutated its input"


def test_merge_ignores_entries_with_a_blank_key():
    merged = analysis.merge_panel_delta(
        None, PanelDelta(new_symptoms=[ReportedSymptom(name="   ")])
    )
    assert merged.symptoms == []


def test_merge_accumulates_across_many_passes():
    panel = None
    for i in range(5):
        panel = analysis.merge_panel_delta(
            panel, PanelDelta(new_symptoms=[ReportedSymptom(name=f"symptom-{i}")])
        )
    assert len(panel.symptoms) == 5


# ── bounded inputs: the cost property ─────────────────────────────────────


@pytest.mark.asyncio
async def test_panel_extraction_only_sees_new_utterances():
    """A pass must not re-send the whole consultation. This is what stops per-pass
    cost from growing with session length."""
    new_only = [_utt("mujhe bukhar hai", seq=99)]
    panel = ClinicalPanel(symptoms=[ReportedSymptom(name="headache")])

    with patch.object(
        analysis.llm, "complete_structured", new=AsyncMock(return_value=PanelDelta())
    ) as mock:
        await analysis.extract_panel_delta(new_only, panel)

    prompt = mock.await_args.args[0]
    assert "mujhe bukhar hai" in prompt
    assert "headache" in prompt, "the panel so far must still anchor the extraction"
    assert (
        mock.await_args.kwargs["fast"] is True
    ), "extraction must stay on the cheap model"


@pytest.mark.asyncio
async def test_panel_extraction_input_does_not_grow_with_session_length():
    captured: list[int] = []

    async def capture(prompt, *_args, **_kwargs):
        captured.append(len(prompt))
        return PanelDelta()

    panel = ClinicalPanel()
    with patch.object(analysis.llm, "complete_structured", new=capture):
        for pass_no in range(10):
            # One interval's worth of speech per pass, regardless of what came before.
            await analysis.extract_panel_delta(
                [_utt("some new speech", seq=pass_no)], panel
            )

    assert (
        max(captured) - min(captured) < 50
    ), f"prompt size drifted across passes: {captured}"


@pytest.mark.asyncio
async def test_suggest_reads_the_panel_not_the_whole_transcript():
    """The panel is already a structured summary of the consultation, so suggestions
    do not need the raw transcript — only a short tail for immediate context."""
    panel = ClinicalPanel(symptoms=[ReportedSymptom(name="fever")])
    recent = [_utt("latest exchange", seq=0)]

    with patch.object(
        analysis.llm,
        "complete_structured",
        new=AsyncMock(return_value=LiveSuggestions()),
    ) as mock:
        await analysis.suggest(panel, recent)

    prompt = mock.await_args.args[0]
    assert "fever" in prompt
    assert "latest exchange" in prompt
    assert (
        mock.await_args.kwargs["fast"] is False
    ), "suggestions are the one call worth Sonnet"
    assert mock.await_args.kwargs["max_tokens"] == settings.CABIN_SUGGEST_MAX_TOKENS


@pytest.mark.asyncio
async def test_attribute_roles_window_is_bounded():
    utterances = [_utt(f"utterance-{i}", seq=i) for i in range(30)]
    with patch.object(
        analysis.llm,
        "complete_structured",
        new=AsyncMock(return_value=RoleAttribution()),
    ) as mock:
        await analysis.attribute_roles(utterances, window=8)

    prompt = mock.await_args.args[0]
    assert "utterance-29" in prompt
    assert "utterance-21" not in prompt
    assert mock.await_args.kwargs["temperature"] == 0.0


def test_render_utterances_labels_roles_and_skips_blanks():
    text = analysis.render_utterances(
        [
            _utt("kya dard hai?", UtteranceRole.DOCTOR, 0),
            _utt("   ", UtteranceRole.PATIENT, 1),
            _utt("haan", UtteranceRole.PATIENT, 2),
        ]
    )
    assert text == "[doctor] kya dard hai?\n[patient] haan"


@pytest.mark.asyncio
async def test_role_prompt_still_permits_correcting_an_earlier_label():
    """Output is trimmed by asking only for unknown-or-corrected labels, but the
    ability to relabel matters — later context often reveals who was speaking."""
    utterances = [
        _utt("aap kaise hain?", UtteranceRole.PATIENT, 0),  # mislabelled earlier
        _utt("mujhe bukhar hai", UtteranceRole.UNKNOWN, 1),
    ]
    with patch.object(
        analysis.llm,
        "complete_structured",
        new=AsyncMock(return_value=RoleAttribution()),
    ) as mock:
        await analysis.attribute_roles(utterances)

    system = mock.await_args.kwargs["system"]
    assert "correcting" in mock.await_args.args[0] or "correct" in system.lower()
    # Context for already-labelled utterances must still be sent, or a correction
    # is impossible.
    assert "aap kaise hain?" in mock.await_args.args[0]


# ── reconciliation: what deltas structurally cannot do ────────────────────


@pytest.mark.asyncio
async def test_reconcile_reads_the_whole_transcript():
    """Deltas only ever see the newest slice. Reconciliation must see everything, or
    it cannot spot a correction made long after the original statement."""
    utterances = [
        _utt("teen din se bukhar", seq=0),
        _utt("aur kuch?", UtteranceRole.DOCTOR, 1),
        _utt("nahi, teen hafte se hai actually", seq=2),
    ]
    with patch.object(
        analysis.llm, "complete_structured", new=AsyncMock(return_value=ClinicalPanel())
    ) as mock:
        await analysis.reconcile_panel(utterances, ClinicalPanel())

    prompt = mock.await_args.args[0]
    assert "teen din se bukhar" in prompt
    assert "teen hafte se hai actually" in prompt
    assert mock.await_args.kwargs["fast"] is True
    assert (
        mock.await_args.kwargs["max_tokens"]
        == settings.CABIN_PANEL_RECONCILE_MAX_TOKENS
    )


@pytest.mark.asyncio
async def test_reconcile_returns_a_whole_panel_not_a_delta():
    """It replaces the panel, which is how an entry can be dropped — a delta has no
    way to express a retraction."""
    with patch.object(
        analysis.llm, "complete_structured", new=AsyncMock(return_value=ClinicalPanel())
    ) as mock:
        await analysis.reconcile_panel([_utt("x", seq=0)], None)
    assert mock.await_args.args[1] is ClinicalPanel


def test_reconcile_prompt_states_the_transcript_wins():
    """Without this the model tends to preserve the prior panel and corrections never
    land."""
    system = analysis.RECONCILE_SYSTEM_PROMPT.lower()
    assert "source of truth" in system
    assert "corrected" in system
    assert "retracted" in system or "denied" in system


def test_panel_clinically_changed_detects_a_removal():
    """A retraction removes an entry. The delta gate cannot see that, so reconciliation
    passes use this instead."""
    old = ClinicalPanel(
        diagnoses=[
            DifferentialDiagnosis(
                condition="diabetes", likelihood="High", reasoning="r"
            )
        ]
    )
    assert analysis.panel_clinically_changed(old, ClinicalPanel()) is True


def test_panel_clinically_changed_ignores_question_churn():
    old = ClinicalPanel(symptoms=[ReportedSymptom(name="fever")])
    new = ClinicalPanel(
        symptoms=[ReportedSymptom(name="fever")],
        questions_asked=[AskedQuestion(text="onset"), AskedQuestion(text="allergies")],
    )
    assert analysis.panel_clinically_changed(old, new) is False


def test_panel_clinically_changed_ignores_reworded_detail():
    old = ClinicalPanel(symptoms=[ReportedSymptom(name="fever", detail="3 days")])
    new = ClinicalPanel(symptoms=[ReportedSymptom(name="Fever", detail="three days")])
    assert analysis.panel_clinically_changed(old, new) is False


@pytest.mark.asyncio
async def test_suggest_receives_the_transcript_not_just_the_panel():
    """Differentials are the highest-value output on the screen. Reasoning over a
    structured summary loses the phrasing clinical judgement leans on."""
    panel = ClinicalPanel(symptoms=[ReportedSymptom(name="chest pain")])
    utterances = [
        _utt("seene mein jalan hoti hai khaane ke baad", seq=0),
        _utt("lekin chalne se nahi badhti", seq=1),
    ]
    with patch.object(
        analysis.llm,
        "complete_structured",
        new=AsyncMock(return_value=LiveSuggestions()),
    ) as mock:
        await analysis.suggest(panel, utterances)

    prompt = mock.await_args.args[0]
    assert "seene mein jalan hoti hai khaane ke baad" in prompt
    assert "chalne se nahi badhti" in prompt, "lost the exam-relevant qualifier"
    assert mock.await_args.kwargs["fast"] is False


def test_suggest_token_ceiling_fits_a_full_suggestion_set():
    """Under forced tool-use a truncated response fails to parse, so the doctor gets no
    suggestions at all. ~400 tokens is a realistic full set; the ceiling needs headroom
    above that, not a trim to save output cost."""
    assert settings.CABIN_SUGGEST_MAX_TOKENS >= 700
