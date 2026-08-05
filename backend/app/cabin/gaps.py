"""Gap alerts — what the patient's history says the doctor should have asked.

Fires *during* the consultation rather than after it. A gap the doctor learns about once
the patient has left is a report; the same gap on screen while they are still in the room
is a save, which is the whole point.

Cost discipline: the input is the profile plus the normalised questions already asked —
never the transcript. That is what keeps this call flat regardless of how long the
consultation runs, and it is why this can afford to be a Haiku-tier call on a cadence
rather than a one-off at teardown.
"""

from __future__ import annotations

import logging

from pydantic import BaseModel

from app.agent import llm
from app.cabin.models import ClinicalPanel
from app.clinical.profile import PatientProfile
from app.core.config import settings

log = logging.getLogger(__name__)

GAP_SYSTEM_PROMPT = """You support a doctor during a live consultation. You never speak to
the patient and you never diagnose.

Your job is narrow: given what is already known about this patient, and the questions the
doctor has asked so far in this consultation, name the things a careful clinician would
want to have asked and has not.

Rules:
- Only raise a gap that is grounded in the patient's known history. Do not invent
  conditions, and do not raise generic history-taking questions that any consultation
  would include.
- If the doctor has already covered an area, it is not a gap, even if worded differently.
- Say nothing rather than pad. An empty list is the correct and common answer.
- Each gap is one question the doctor could ask out loud, phrased plainly.
"""

GAP_PROMPT_TEMPLATE = """Known about this patient:
{profile}

Questions the doctor has already asked in this consultation:
{asked}

Return only genuine, history-grounded gaps."""


class Gap(BaseModel):
    condition: str  # the known condition that motivates the question
    question: str  # what the doctor should ask
    rationale: str


class GapAlerts(BaseModel):
    gaps: list[Gap] = []


def gap_key(gap: Gap) -> str:
    """Identity for de-duplication across passes. Mirrors the `_key` idiom in
    analysis.py: normalise, don't fuzzy-match."""
    return f"{' '.join(gap.condition.lower().split())}|{' '.join(gap.question.lower().split())}"


async def detect_gaps(profile: PatientProfile, panel: ClinicalPanel) -> GapAlerts:
    """One bounded Haiku call. Callers gate this — see CabinLiveSession."""
    asked = [q.text for q in panel.questions_asked] if panel else []
    result = await llm.complete_structured(
        GAP_PROMPT_TEMPLATE.format(
            profile=profile.model_dump_json(exclude={"patient_id"}),
            asked="\n".join(f"- {q}" for q in asked) or "(none yet)",
        ),
        GapAlerts,
        system=GAP_SYSTEM_PROMPT,
        fast=True,
        max_tokens=settings.CABIN_GAP_MAX_TOKENS,
    )
    return result  # type: ignore[return-value]
