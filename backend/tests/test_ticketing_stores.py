"""Tests for ticketing stores — all run in-memory, no MongoDB.

Covers: patient uniqueness, session ticket number generation, soft delete,
stale sweep, hospital category seeding, and admin ticket search.
"""
from __future__ import annotations

import os
import time
from datetime import datetime, timedelta

os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-for-pytest-only")

import pytest

from app.ticketing.models import (
    CategoryInfo,
    Hospital,
    TicketCategory,
    TicketSession,
)


# ── fixtures ──────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def isolate_ticketing_stores(monkeypatch):
    """Force all ticketing stores into in-memory mode and reset state between tests."""
    import app.ticketing.patient_store as ps
    import app.ticketing.session_store as ss
    import app.ticketing.hospital_store as hs

    def unavailable():
        raise RuntimeError("MongoDB intentionally unavailable in tests")

    monkeypatch.setattr(ps, "_col", unavailable)
    monkeypatch.setattr(ss, "_col", unavailable)
    monkeypatch.setattr(ss, "_counters_col", unavailable)
    monkeypatch.setattr(hs, "_hospitals_col", unavailable)
    monkeypatch.setattr(hs, "_categories_col", unavailable)

    # Reset in-memory state
    ps._mem.clear()
    ps._phone_index.clear()
    ps._mongo_write_failed = True

    ss._mem.clear()
    ss._mem_by_ticket.clear()
    ss._mongo_write_failed = True
    ss._local_counter = 0

    hs._mem_hospitals.clear()
    hs._mem_categories.clear()
    hs._mongo_write_failed = True

    yield

    ps._mem.clear()
    ps._phone_index.clear()
    ps._mongo_write_failed = False
    ss._mem.clear()
    ss._mem_by_ticket.clear()
    ss._mongo_write_failed = False
    ss._local_counter = 0
    hs._mem_hospitals.clear()
    hs._mem_categories.clear()
    hs._mongo_write_failed = False


# ── patient store ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_patient_upsert_creates_new_patient():
    from app.ticketing.patient_store import ticket_patient_store
    p = await ticket_patient_store.upsert(phone="9876543210", name="Priya", age=28)
    assert p.phone == "9876543210"
    assert p.name == "Priya"
    assert p.age == 28
    assert p.patient_id


@pytest.mark.asyncio
async def test_patient_upsert_same_phone_returns_same_patient():
    from app.ticketing.patient_store import ticket_patient_store
    p1 = await ticket_patient_store.upsert(phone="9000000001")
    p2 = await ticket_patient_store.upsert(phone="9000000001", name="Rahul")
    assert p1.patient_id == p2.patient_id, "same phone must return same patient"


@pytest.mark.asyncio
async def test_patient_upsert_different_phone_creates_different_patients():
    from app.ticketing.patient_store import ticket_patient_store
    p1 = await ticket_patient_store.upsert(phone="9000000002")
    p2 = await ticket_patient_store.upsert(phone="9000000003")
    assert p1.patient_id != p2.patient_id


@pytest.mark.asyncio
async def test_patient_upsert_updates_name_on_revisit():
    from app.ticketing.patient_store import ticket_patient_store
    await ticket_patient_store.upsert(phone="9111111111")
    updated = await ticket_patient_store.upsert(phone="9111111111", name="Sunita")
    assert updated.name == "Sunita"


@pytest.mark.asyncio
async def test_patient_upsert_does_not_erase_existing_name_with_none():
    """A new session that doesn't collect name yet should not blank out a known name."""
    from app.ticketing.patient_store import ticket_patient_store
    await ticket_patient_store.upsert(phone="9222222222", name="Amit")
    result = await ticket_patient_store.upsert(phone="9222222222")  # no name param
    assert result.name == "Amit", "name was erased by a None update"


@pytest.mark.asyncio
async def test_patient_get_by_patient_id():
    from app.ticketing.patient_store import ticket_patient_store
    created = await ticket_patient_store.upsert(phone="9333333333", age=45)
    fetched = await ticket_patient_store.get(created.patient_id)
    assert fetched is not None
    assert fetched.patient_id == created.patient_id
    assert fetched.age == 45


@pytest.mark.asyncio
async def test_patient_get_returns_none_for_unknown_id():
    from app.ticketing.patient_store import ticket_patient_store
    result = await ticket_patient_store.get("nonexistent-id")
    assert result is None


@pytest.mark.asyncio
async def test_patient_phone_is_globally_unique_across_hospitals():
    """Phone uniqueness is global — same phone at two hospitals is the same patient."""
    from app.ticketing.patient_store import ticket_patient_store
    p1 = await ticket_patient_store.upsert(phone="9444444444")
    p2 = await ticket_patient_store.upsert(phone="9444444444")
    assert p1.patient_id == p2.patient_id


# ── session store — ticket number ─────────────────────────────


@pytest.mark.asyncio
async def test_session_create_assigns_ticket_number():
    from app.ticketing.session_store import ticket_session_store
    s = TicketSession(hospital_id="h1", patient_id="p1")
    await ticket_session_store.create(s)
    assert s.ticket_number is not None
    assert s.ticket_number.startswith("TKT-")


@pytest.mark.asyncio
async def test_ticket_numbers_are_sequential():
    from app.ticketing.session_store import ticket_session_store
    s1 = TicketSession(hospital_id="h1", patient_id="p1")
    s2 = TicketSession(hospital_id="h1", patient_id="p1")
    await ticket_session_store.create(s1)
    await ticket_session_store.create(s2)
    n1 = int(s1.ticket_number.split("-")[1])
    n2 = int(s2.ticket_number.split("-")[1])
    assert n2 == n1 + 1, f"ticket numbers not sequential: {s1.ticket_number}, {s2.ticket_number}"


@pytest.mark.asyncio
async def test_ticket_number_format_is_six_digits():
    from app.ticketing.session_store import ticket_session_store
    s = TicketSession(hospital_id="h1", patient_id="p1")
    await ticket_session_store.create(s)
    parts = s.ticket_number.split("-")
    assert len(parts) == 2
    assert len(parts[1]) == 6
    assert parts[1].isdigit()


@pytest.mark.asyncio
async def test_get_by_ticket_number():
    from app.ticketing.session_store import ticket_session_store
    s = TicketSession(hospital_id="h1", patient_id="p1")
    await ticket_session_store.create(s)
    found = await ticket_session_store.get_by_ticket_number(s.ticket_number)
    assert found is not None
    assert found.session_id == s.session_id


@pytest.mark.asyncio
async def test_get_by_ticket_number_wrong_hospital_returns_none():
    from app.ticketing.session_store import ticket_session_store
    s = TicketSession(hospital_id="h1", patient_id="p1")
    await ticket_session_store.create(s)
    found = await ticket_session_store.get_by_ticket_number(s.ticket_number, hospital_id="h2")
    assert found is None


# ── session store — CRUD ──────────────────────────────────────


@pytest.mark.asyncio
async def test_session_get_returns_none_for_unknown():
    from app.ticketing.session_store import ticket_session_store
    assert await ticket_session_store.get("does-not-exist") is None


@pytest.mark.asyncio
async def test_session_get_scoped_by_hospital_id():
    from app.ticketing.session_store import ticket_session_store
    s = TicketSession(hospital_id="h1", patient_id="p1")
    await ticket_session_store.create(s)
    assert await ticket_session_store.get(s.session_id, hospital_id="h1") is not None
    assert await ticket_session_store.get(s.session_id, hospital_id="h2") is None


@pytest.mark.asyncio
async def test_session_update_persists_changes():
    from app.ticketing.session_store import ticket_session_store
    s = TicketSession(hospital_id="h1", patient_id="p1")
    await ticket_session_store.create(s)
    s.phase = "consultation"
    s.turn_count = 3
    await ticket_session_store.update(s)
    fetched = await ticket_session_store.get(s.session_id)
    assert fetched.phase == "consultation"
    assert fetched.turn_count == 3


# ── session store — soft delete ───────────────────────────────


@pytest.mark.asyncio
async def test_soft_delete_sets_deleted_at():
    from app.ticketing.session_store import ticket_session_store
    s = TicketSession(hospital_id="h1", patient_id="p1")
    await ticket_session_store.create(s)
    ok = await ticket_session_store.soft_delete(s.session_id, "h1")
    assert ok is True
    fetched = await ticket_session_store.get(s.session_id)
    assert fetched.deleted_at is not None


@pytest.mark.asyncio
async def test_soft_delete_wrong_hospital_fails():
    from app.ticketing.session_store import ticket_session_store
    s = TicketSession(hospital_id="h1", patient_id="p1")
    await ticket_session_store.create(s)
    ok = await ticket_session_store.soft_delete(s.session_id, "h2")
    assert ok is False


@pytest.mark.asyncio
async def test_list_excludes_deleted_by_default():
    from app.ticketing.session_store import ticket_session_store
    s = TicketSession(hospital_id="h1", patient_id="p1")
    await ticket_session_store.create(s)
    await ticket_session_store.soft_delete(s.session_id, "h1")
    rows = await ticket_session_store.list_for_hospital("h1")
    assert all(r.get("session_id") != s.session_id for r in rows)


@pytest.mark.asyncio
async def test_list_includes_deleted_when_flag_set():
    from app.ticketing.session_store import ticket_session_store
    s = TicketSession(hospital_id="h1", patient_id="p1")
    await ticket_session_store.create(s)
    await ticket_session_store.soft_delete(s.session_id, "h1")
    rows = await ticket_session_store.list_for_hospital("h1", include_deleted=True)
    assert any(r.get("session_id") == s.session_id for r in rows)


# ── session store — stale sweep ───────────────────────────────


@pytest.mark.asyncio
async def test_stale_active_session_is_flipped_to_partial(monkeypatch):
    """A session that is still 'active' but hasn't been updated in > STALE_MINUTES
    should be lazily flipped to 'partial' on the next read."""
    import app.ticketing.session_store as ss
    from app.ticketing.session_store import ticket_session_store

    s = TicketSession(hospital_id="h1", patient_id="p1")
    await ticket_session_store.create(s)

    # Back-date updated_at to simulate a stale session
    stale_time = datetime.utcnow() - timedelta(minutes=ss.STALE_MINUTES + 5)
    ss._mem[s.session_id]["updated_at"] = stale_time.isoformat()
    ss._mem[s.session_id]["status"] = "active"

    fetched = await ticket_session_store.get(s.session_id)
    assert fetched.status == "partial", "stale active session was not flipped"


@pytest.mark.asyncio
async def test_completed_session_not_flipped_to_partial(monkeypatch):
    import app.ticketing.session_store as ss
    from app.ticketing.session_store import ticket_session_store

    s = TicketSession(hospital_id="h1", patient_id="p1")
    s.status = "completed"
    await ticket_session_store.create(s)

    stale_time = datetime.utcnow() - timedelta(minutes=ss.STALE_MINUTES + 5)
    ss._mem[s.session_id]["updated_at"] = stale_time.isoformat()

    fetched = await ticket_session_store.get(s.session_id)
    assert fetched.status == "completed", "completed session was wrongly flipped"


# ── session store — list + search ────────────────────────────


@pytest.mark.asyncio
async def test_list_filters_by_status():
    from app.ticketing.session_store import ticket_session_store
    s1 = TicketSession(hospital_id="h1", patient_id="p1", status="completed")
    s2 = TicketSession(hospital_id="h1", patient_id="p2", status="partial")
    await ticket_session_store.create(s1)
    await ticket_session_store.create(s2)
    rows = await ticket_session_store.list_for_hospital("h1", status="completed")
    assert all(r.get("status") == "completed" for r in rows)


@pytest.mark.asyncio
async def test_list_search_by_ticket_number():
    from app.ticketing.session_store import ticket_session_store
    s = TicketSession(hospital_id="h1", patient_id="p1")
    await ticket_session_store.create(s)
    rows = await ticket_session_store.list_for_hospital(
        "h1", search_ticket=s.ticket_number
    )
    assert len(rows) == 1
    assert rows[0]["ticket_number"] == s.ticket_number


@pytest.mark.asyncio
async def test_list_for_patient_returns_sessions():
    from app.ticketing.session_store import ticket_session_store
    s1 = TicketSession(hospital_id="h1", patient_id="patient-x")
    s2 = TicketSession(hospital_id="h1", patient_id="patient-y")
    await ticket_session_store.create(s1)
    await ticket_session_store.create(s2)
    rows = await ticket_session_store.list_for_patient("patient-x")
    assert len(rows) == 1
    assert rows[0]["patient_id"] == "patient-x"


# ── hospital store — seeding ──────────────────────────────────


@pytest.mark.asyncio
async def test_hospital_create_seeds_default_categories():
    from app.ticketing.hospital_store import hospital_store
    from app.ticketing.models import DEFAULT_CATEGORIES
    h = Hospital(slug="test-hospital", name="Test Hospital")
    await hospital_store.create(h)
    cats = await hospital_store.list_categories(h.hospital_id)
    assert len(cats) == len(DEFAULT_CATEGORIES)
    keys = {c.key for c in cats}
    assert "general_medicine" in keys
    assert "gynecology" in keys


@pytest.mark.asyncio
async def test_hospital_get_by_slug():
    from app.ticketing.hospital_store import hospital_store
    h = Hospital(slug="slug-test", name="Slug Test Hospital")
    await hospital_store.create(h)
    found = await hospital_store.get_by_slug("slug-test")
    assert found is not None
    assert found.hospital_id == h.hospital_id


@pytest.mark.asyncio
async def test_hospital_get_by_slug_unknown_returns_none():
    from app.ticketing.hospital_store import hospital_store
    assert await hospital_store.get_by_slug("does-not-exist") is None


@pytest.mark.asyncio
async def test_category_toggle_inactive():
    from app.ticketing.hospital_store import hospital_store
    h = Hospital(slug="cat-toggle-test", name="Toggle Test")
    await hospital_store.create(h)
    cats = await hospital_store.list_categories(h.hospital_id)
    cat = cats[0]
    updated = await hospital_store.update_category(cat.category_id, h.hospital_id, active=False)
    assert updated is not None
    assert updated.active is False


@pytest.mark.asyncio
async def test_list_categories_active_only_excludes_inactive():
    from app.ticketing.hospital_store import hospital_store
    h = Hospital(slug="active-only-test", name="Active Only Test")
    await hospital_store.create(h)
    cats = await hospital_store.list_categories(h.hospital_id)
    cat = cats[0]
    await hospital_store.update_category(cat.category_id, h.hospital_id, active=False)
    active_cats = await hospital_store.list_categories(h.hospital_id, active_only=True)
    inactive_cats = await hospital_store.list_categories(h.hospital_id, active_only=False)
    assert all(c.active for c in active_cats)
    assert len(inactive_cats) > len(active_cats)
