"""Tests for ticketing models, IST helper, and session store ticket numbering.

None of these touch MongoDB or any LLM — pure Python, runs offline.
"""
from __future__ import annotations

import os
from datetime import datetime, timezone, timedelta

os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-for-pytest-only")

import pytest

from app.ticketing.models import (
    CategoryInfo,
    Hospital,
    TicketCategory,
    TicketFlag,
    TicketPatient,
    TicketQAEntry,
    TicketSession,
    to_ist_str,
)


# ── to_ist_str ────────────────────────────────────────────────


def test_to_ist_str_converts_utc_to_ist():
    # UTC midnight → IST 05:30
    dt = datetime(2026, 8, 24, 0, 0, 0, tzinfo=timezone.utc)
    result = to_ist_str(dt)
    assert result == "2026-08-24 05:30:00 IST"


def test_to_ist_str_handles_none():
    assert to_ist_str(None) is None


def test_to_ist_str_naive_datetime_treated_as_utc():
    dt = datetime(2026, 8, 24, 18, 30, 0)  # naive
    result = to_ist_str(dt)
    assert result == "2026-08-25 00:00:00 IST"


# ── TicketPatient ─────────────────────────────────────────────


def test_ticket_patient_has_no_hospital_id():
    """Phone is globally unique — hospital_id must not exist on patient."""
    patient = TicketPatient(phone="9876543210")
    assert not hasattr(patient, "hospital_id") or "hospital_id" not in patient.model_fields
    assert patient.phone == "9876543210"


def test_ticket_patient_defaults():
    p = TicketPatient(phone="9000000000")
    assert p.name is None
    assert p.age is None
    assert p.gender is None
    assert p.patient_id  # UUID assigned


# ── TicketSession ─────────────────────────────────────────────


def test_ticket_session_defaults():
    s = TicketSession(hospital_id="h1", patient_id="p1")
    assert s.phase == "triage"
    assert s.status == "active"
    assert s.deleted_at is None
    assert s.ticket_number is None  # assigned by store, not constructor
    assert s.turn_count == 0
    assert s.qa_log == []
    assert s.flags == []


def test_ticket_session_soft_delete_field():
    s = TicketSession(hospital_id="h1", patient_id="p1")
    s.deleted_at = datetime.utcnow()
    assert s.deleted_at is not None


def test_ticket_session_category_info():
    s = TicketSession(hospital_id="h1", patient_id="p1")
    s.category = CategoryInfo(key="gynecology", label="Gynaecology", source="auto")
    assert s.category.source == "auto"
    assert s.category.key == "gynecology"


def test_ticket_session_accumulates_flags():
    s = TicketSession(hospital_id="h1", patient_id="p1")
    s.flags.append(TicketFlag(flag_type="RED_FLAG", description="High fever"))
    s.flags.append(TicketFlag(flag_type="CRITICAL_RED_FLAG", description="Chest pain"))
    assert len(s.flags) == 2
    assert s.flags[1].flag_type == "CRITICAL_RED_FLAG"


def test_ticket_session_qa_log():
    s = TicketSession(hospital_id="h1", patient_id="p1")
    s.qa_log.append(TicketQAEntry(
        question_id="triage_1",
        question_text="Aapko kya takleef hai?",
        answer="Bukhar hai",
    ))
    assert len(s.qa_log) == 1
    assert s.qa_log[0].answer == "Bukhar hai"


# ── Hospital / Category ───────────────────────────────────────


def test_hospital_defaults():
    h = Hospital(slug="aiims-delhi", name="AIIMS Delhi")
    assert h.default_language == "hi"
    assert h.hospital_id  # UUID assigned


def test_ticket_category_defaults():
    c = TicketCategory(hospital_id="h1", key="general_medicine", label="General Medicine")
    assert c.active is True
    assert c.category_id  # UUID assigned


def test_ticket_category_key_is_string():
    c = TicketCategory(hospital_id="h1", key="ent", label="ENT")
    assert c.key == "ent"
