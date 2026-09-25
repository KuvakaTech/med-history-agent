"""Department-specific triage routing hints and consultation supplements.

Generic departments use the shared 8-area screener only. Keys here match
TicketCategory.key (e.g. orthopedics).
"""

from __future__ import annotations

# Shown to triage LLMs (never read aloud) to improve routing from symptoms.
TRIAGE_ROUTING_HINTS: dict[str, str] = {
    "orthopedics": (
        "orthopedics (Orthopaedics): bones, joints, muscles, ligaments, or spine — "
        "fracture, sprain/strain, dislocation, arthritis flare, back or neck pain, "
        "knee/shoulder/hip pain, sports injury, fall or trauma, cannot walk or bear weight, "
        "joint stiffness, locking, or giving way."
    ),
}

# Appended to the consultation system instruction for that department.
CONSULTATION_SUPPLEMENTS: dict[str, str] = {
    "orthopedics": """\
──────────────────────────────────────
ORTHOPAEDICS — department-specific history (in addition to the 8 required areas)
──────────────────────────────────────
Prioritize ONE question at a time about:
• Exact body part / joint (left vs right if relevant)
• How it started — injury (fall, twist, accident, sports) vs gradual wear-and-tear
• Can they walk, climb stairs, or use the limb normally? Any inability to bear weight?
• Swelling, bruising, visible deformity, open wound, or bleeding
• Range of motion — stiffness, locking, catching, or joint giving way
• Prior fracture, surgery, or metal implant on that area
• Any X-ray, MRI, or plaster/splint already done elsewhere
• Pain at rest vs only on movement; night pain waking them from sleep (note as red flag if severe)

Do not diagnose. Do not recommend surgery or specific treatments.""",
}


def triage_routing_block(category_keys: list[str]) -> str:
    """Optional routing cues for departments that have playbooks."""
    lines: list[str] = []
    for key in category_keys:
        hint = TRIAGE_ROUTING_HINTS.get(key)
        if hint:
            lines.append(f"  • {hint}")
    if not lines:
        return ""
    return (
        "\nROUTING HINTS (internal — never read aloud; use to infer category_key):\n"
        + "\n".join(lines)
    )


def consultation_supplement(category_key: str | None) -> str:
    if not category_key:
        return ""
    return CONSULTATION_SUPPLEMENTS.get(category_key.strip().lower(), "")
