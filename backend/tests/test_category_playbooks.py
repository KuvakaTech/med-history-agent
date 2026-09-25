"""Department playbooks for ticketing."""

from app.ticketing.category_playbooks import (
    consultation_supplement,
    triage_routing_block,
)
from app.ticketing.consultation_engine import ConsultationEngine
from app.ticketing.models import TicketCategory
from app.ticketing.prompts_v2 import consultation_system_instruction, triage_system_instruction


def test_orthopedics_triage_routing_hint():
    block = triage_routing_block(["general_medicine", "orthopedics"])
    assert "orthopedics" in block
    assert "fracture" in block.lower()


def test_orthopedics_consultation_supplement():
    text = consultation_supplement("orthopedics")
    assert "ORTHOPAEDICS" in text
    assert "bear weight" in text.lower()


def test_consultation_engine_orthopedics_system_includes_playbook():
    engine = ConsultationEngine(
        category_label="Orthopaedics",
        category_key="orthopedics",
    )
    assert "ORTHOPAEDICS" in engine._system


def test_prompts_v2_orthopedics_consultation():
    text = consultation_system_instruction(
        category_label="Orthopaedics",
        language="hi",
        name="Ravi",
        age="45",
        gender="male",
        routing_summary="knee pain after fall",
        category_key="orthopedics",
    )
    assert "Orthopaedics" in text
    assert "bear weight" in text.lower()


def test_prompts_v2_triage_includes_orthopedics_routing():
    cats = [
        TicketCategory(hospital_id="h1", key="orthopedics", label="Orthopaedics"),
    ]
    text = triage_system_instruction(cats, language="hi", gender="male")
    assert "orthopedics" in text
    assert "ROUTING HINTS" in text
