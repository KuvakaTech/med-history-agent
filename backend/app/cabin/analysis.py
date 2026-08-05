"""Analysis calls for the cabin live loop: role attribution, panel extraction,
and gated suggestions.

The panel is maintained by two complementary passes, because neither alone is both
responsive and correct:

  * `extract_panel_delta` runs on the fast cadence (~8s). It sees only the utterances
    since the last pass, returns only what is new, and is merged in Python. Cheap and
    immediate — but it cannot revise or drop an entry, and it never looks at an
    utterance twice.
  * `reconcile_panel` runs periodically and at end of session. It reads the *whole*
    transcript and rebuilds the panel from scratch, so a patient correcting themselves
    ("three days" -> "actually three weeks"), retracting something ("I don't have
    diabetes"), or anything a delta pass missed all get fixed. The end-of-session pass
    is what makes the persisted record authoritative — it is the input to coding and
    insurance downstream, so it must reflect the full conversation, not an accumulation
    of increments.

Suggestions read the real transcript, not a summary. Differentials are the highest-value
clinical output here and the exact words a patient used carry signal a structured panel
loses; the call is gated so it runs rarely enough to afford that.

Prompt caching is deliberately *not* relied on: the fast model is Haiku 4.5, whose
minimum cacheable prefix is 4096 tokens, and a whole 20-minute consult is only about
4,500 tokens of transcript. A cache breakpoint would go unused for nearly the entire
session, and it addresses input tokens when output was the larger cost anyway.

Never call a provider SDK directly — everything goes through app.agent.llm.
"""

from __future__ import annotations

from typing import Optional

from app.agent import llm
from app.cabin.models import (
    ClinicalPanel,
    LiveSuggestions,
    PanelDelta,
    RoleAttribution,
    Utterance,
)
from app.core.config import settings

ROLE_SYSTEM_PROMPT = """\
You are labeling speaker roles in a live clinical consultation transcript from an \
Indian outpatient clinic. Three possible roles: doctor, patient, attendee \
(a family member or companion accompanying the patient). Utterances may be in \
Hindi, English, Marathi, Gujarati, or a mix.

Use conversational cues, not just content: the doctor asks clinical questions, \
gives instructions, and leads the exam. The patient answers about their own body \
and symptoms. An attendee speaks about the patient in the third person or answers \
on the patient's behalf. A speaker_id hint may be present — treat it only as a \
weak clustering signal, not ground truth; utterances with the same speaker_id are \
likely (not certainly) the same person.

You see a window of recent utterances for context, but return labels only for the ones \
still marked unknown, plus any earlier utterance whose existing label you are now \
confident is wrong — later context often makes an earlier speaker obvious. Do not \
repeat a label you already agree with. If an utterance is genuinely ambiguous, leave \
it unknown rather than guessing."""

ROLE_PROMPT_TEMPLATE = """\
Utterances (utterance_id, current role, speaker_id hint, text):
{utterances}

Return labels only for utterances that are still unknown or that you are correcting."""

PANEL_SYSTEM_PROMPT = """\
You extract new clinical facts from the latest stretch of a doctor-patient \
consultation (Hindi/English/Marathi/Gujarati, doctor-led).

You are given the panel built so far and only the newest utterances. Return ONLY what \
those new utterances add — do not restate anything already in the panel, and return \
empty lists when they add nothing. Returning an entry that is already present is \
harmless but wasteful; inventing one is not acceptable.

Only give a medication a dose or frequency if the transcript actually states one. If a \
drug is mentioned by name alone ("we'll start you on metformin"), leave dose and \
frequency null rather than filling in a typical value — a fabricated dose on a \
clinical screen is a patient-safety problem. Never invent a symptom, diagnosis, test, \
or medication that was not said.

If new utterances supply a detail the panel was missing (a duration for a symptom \
already listed, a dose for a drug already listed), return that entry again with the \
new field filled in — it will be merged into the existing one, not duplicated.

new_questions_asked should name distinct topics the doctor has covered \
("onset", "past history", "allergies"), not a verbatim copy of every question."""

PANEL_PROMPT_TEMPLATE = """\
Panel so far:
{panel}

Newest utterances:
{new_utterances}

Return only what the newest utterances add."""

RECONCILE_SYSTEM_PROMPT = """\
You rebuild the structured panel for a doctor-patient consultation \
(Hindi/English/Marathi/Gujarati, doctor-led) from the complete transcript.

The transcript is the source of truth, not the previous panel. Read the whole \
conversation and return the panel as it should stand now:

- If the patient corrected themselves later ("teen din" then "nahi, teen hafte"), use \
  the corrected value, not the first one.
- If something was retracted or denied ("mujhe diabetes nahi hai"), leave it out even \
  if an earlier line implied it.
- Include anything the transcript supports that the previous panel is missing.
- Drop anything the previous panel contains that the transcript does not support.

Only give a medication a dose or frequency the transcript actually states — never fill \
in a typical value. Never invent a symptom, diagnosis, test, or medication that was \
not said. questions_asked should name distinct topics the doctor covered, not every \
question verbatim."""

RECONCILE_PROMPT_TEMPLATE = """\
Previous panel (for reference only — the transcript wins where they disagree):
{panel}

Full consultation transcript:
{transcript}

Return the corrected panel for the whole consultation."""

SUGGEST_SYSTEM_PROMPT = """\
You are assisting a doctor during a live consultation (physician-support only — \
never state a diagnosis as confirmed; this is not shown to the patient). You are given \
the structured panel extracted so far and the consultation transcript. Where they \
disagree, trust the transcript — how a patient phrased something often carries signal \
the structured panel loses.

Suggest: up to 4 questions the doctor has not yet asked (skip anything already listed \
under questions_asked), differential diagnoses with reasoning, tests worth \
considering, and any red flags. Be concise — this renders on a screen the doctor \
glances at mid-consultation, not a report."""

SUGGEST_PROMPT_TEMPLATE = """\
Panel extracted so far:
{panel}

Consultation transcript:
{transcript}

Return live suggestions for the doctor."""


def render_utterances(utterances: list[Utterance]) -> str:
    return "\n".join(f"[{u.role.value}] {u.text}" for u in utterances if u.text.strip())


async def attribute_roles(
    utterances: list[Utterance], window: int = 8
) -> RoleAttribution:
    """Labels the last `window` utterances. Later calls may relabel earlier ones
    as context clarifies — callers apply the returned labels as idempotent patches."""
    recent = utterances[-window:]
    lines = "\n".join(
        f"[{u.utterance_id}] (currently: {u.role.value}, speaker_id: {u.speaker_id or 'none'}) {u.text}"
        for u in recent
    )
    result = await llm.complete_structured(
        ROLE_PROMPT_TEMPLATE.format(utterances=lines or "(none yet)"),
        RoleAttribution,
        system=ROLE_SYSTEM_PROMPT,
        temperature=0.0,
        fast=True,
        max_tokens=512,
    )
    return result  # type: ignore[return-value]


async def extract_panel_delta(
    new_utterances: list[Utterance], panel: Optional[ClinicalPanel]
) -> PanelDelta:
    """Extracts only what the newest utterances add to the panel.

    Both sides of this call are bounded: the input is the current panel plus one
    interval's worth of speech, and the output is whatever is new (often nothing).
    """
    result = await llm.complete_structured(
        PANEL_PROMPT_TEMPLATE.format(
            panel=(
                panel.model_dump_json(exclude={"updated_at"}) if panel else "(empty)"
            ),
            new_utterances=render_utterances(new_utterances) or "(none)",
        ),
        PanelDelta,
        system=PANEL_SYSTEM_PROMPT,
        fast=True,
        max_tokens=settings.CABIN_PANEL_MAX_TOKENS,
    )
    return result  # type: ignore[return-value]


async def reconcile_panel(
    utterances: list[Utterance], panel: Optional[ClinicalPanel]
) -> ClinicalPanel:
    """Rebuilds the panel from the full transcript, correcting anything the incremental
    deltas got wrong or missed.

    This is the pass that catches patient self-corrections and retractions — a delta
    can only ever add. Runs periodically during the consult and once at the end, where
    it makes the persisted record authoritative rather than an accumulation of guesses.
    """
    result = await llm.complete_structured(
        RECONCILE_PROMPT_TEMPLATE.format(
            panel=(
                panel.model_dump_json(exclude={"updated_at"}) if panel else "(empty)"
            ),
            transcript=render_utterances(utterances) or "(none)",
        ),
        ClinicalPanel,
        system=RECONCILE_SYSTEM_PROMPT,
        fast=True,
        max_tokens=settings.CABIN_PANEL_RECONCILE_MAX_TOKENS,
    )
    return result  # type: ignore[return-value]


async def suggest(panel: ClinicalPanel, utterances: list[Utterance]) -> LiveSuggestions:
    """The expensive (Sonnet) call — only invoked when a delta brought something
    clinically new.

    Gets the real transcript rather than a summary of it: differentials are the
    highest-value clinical output on the screen, and a structured panel loses the
    phrasing, hedging and sequence that clinical reasoning leans on. The gate keeps
    this rare enough to afford.
    """
    result = await llm.complete_structured(
        SUGGEST_PROMPT_TEMPLATE.format(
            panel=panel.model_dump_json(exclude={"updated_at"}),
            transcript=render_utterances(utterances) or "(none)",
        ),
        LiveSuggestions,
        system=SUGGEST_SYSTEM_PROMPT,
        fast=False,
        max_tokens=settings.CABIN_SUGGEST_MAX_TOKENS,
    )
    return result  # type: ignore[return-value]


# ── merging deltas into the panel (pure, no LLM) ──────────────────────────

_MERGE_SPECS = (
    ("symptoms", "new_symptoms", "name"),
    ("diagnoses", "new_diagnoses", "condition"),
    ("tests", "new_tests", "name"),
    ("medications", "new_medications", "drug_name"),
    ("questions_asked", "new_questions_asked", "text"),
)

# Fields where a later mention legitimately replaces the earlier value rather than
# being ignored. Two reasons a field lands here:
#   - it describes current state, not a fixed fact ("considered" -> "ordered")
#   - the patient can correct it, and keeping the first answer would be clinically
#     wrong ("three days" -> "actually three weeks" changes the differential)
# Anything not listed is only filled in when previously unknown, so a vague later
# mention cannot erase detail already captured.
_STATE_FIELDS = {
    "status",
    "action",
    "likelihood",
    "detail",
    "dose",
    "frequency",
    "reasoning",
}


def _key(item: object, field: str) -> str:
    return str(getattr(item, field, "")).strip().lower()


def _absorb(existing: object, incoming: object) -> None:
    """Folds a repeat mention into the entry already on the panel.

    Fields in _STATE_FIELDS take the newer value, so a patient correcting a duration or
    a doctor firming up a dose lands on the record. Everything else is only filled in
    when it was unknown, so a vaguer later mention cannot erase detail already
    captured. A `None` never overwrites anything.
    """
    for field in type(incoming).model_fields:  # type: ignore[attr-defined]
        new_value = getattr(incoming, field, None)
        if new_value is None:
            continue
        if field in _STATE_FIELDS or getattr(existing, field, None) is None:
            setattr(existing, field, new_value)


def panel_clinically_changed(old: Optional[ClinicalPanel], new: ClinicalPanel) -> bool:
    """Whether a reconciliation altered the clinical content (not just wording).

    Decides whether a reconciliation pass should re-run suggestions. Deltas use
    `has_clinical_change()` for the same purpose; a reconciliation can additionally
    *remove* entries, which this catches and a delta cannot express.
    """
    if old is None:
        return bool(new.symptoms or new.diagnoses or new.tests or new.medications)

    def keys(panel: ClinicalPanel, attr: str, field: str) -> set[str]:
        return {_key(item, field) for item in getattr(panel, attr)}

    return any(
        keys(old, panel_attr, key_field) != keys(new, panel_attr, key_field)
        for panel_attr, _delta_attr, key_field in _MERGE_SPECS
        if panel_attr != "questions_asked"
    )


def merge_panel_delta(
    panel: Optional[ClinicalPanel], delta: PanelDelta
) -> ClinicalPanel:
    """Merges a delta into the panel, de-duplicating by normalised name.

    Deterministic and side-effect free on its inputs — the model proposes, this decides.
    Doing the merge here rather than asking the model to restate the whole panel is what
    keeps output tokens flat.
    """
    merged = panel.model_copy(deep=True) if panel is not None else ClinicalPanel()

    for panel_attr, delta_attr, key_field in _MERGE_SPECS:
        current = getattr(merged, panel_attr)
        index = {_key(item, key_field): item for item in current}
        for incoming in getattr(delta, delta_attr):
            key = _key(incoming, key_field)
            if not key:
                continue
            existing = index.get(key)
            if existing is None:
                current.append(incoming)
                index[key] = incoming
            else:
                _absorb(existing, incoming)

    return merged
