"""Cross-worker lease semantics, including the fail-open contract.

No real MongoDB: a fake collection stands in, so the atomicity that actually lives in
the query shape is asserted at the query level.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from pymongo.errors import DuplicateKeyError

from app.cabin import leases
from app.core.config import settings


class FakeResult:
    def __init__(self, matched_count: int = 1) -> None:
        self.matched_count = matched_count


class FakeCollection:
    """Records the filters it was handed and replays scripted outcomes."""

    def __init__(self) -> None:
        self.update_filters: list[dict] = []
        self.delete_filters: list[dict] = []
        self.count_filters: list[dict] = []
        self.raise_duplicate = False
        self.matched = 1
        self.count = 0

    async def update_one(self, flt, update, upsert=False):
        self.update_filters.append({"filter": flt, "update": update, "upsert": upsert})
        if self.raise_duplicate:
            raise DuplicateKeyError("live lease exists")
        return FakeResult(self.matched)

    async def delete_one(self, flt):
        self.delete_filters.append(flt)
        return FakeResult()

    async def count_documents(self, flt):
        self.count_filters.append(flt)
        return self.count


@pytest.fixture
def col(monkeypatch):
    """Overrides the autouse isolate_cabin_leases fixture with a working fake."""
    fake = FakeCollection()
    monkeypatch.setattr(leases, "_col", lambda: fake)
    return fake


# ── acquire ───────────────────────────────────────────────────────────────


async def test_acquire_upserts_conditionally_on_an_elapsed_expiry(col):
    """The whole race is decided by this one query, so it is asserted directly: take the
    lease only when absent or expired, and let the _id unique index reject the rest."""
    assert await leases.acquire("sess-1", "doc-a") is True

    call = col.update_filters[0]
    assert call["filter"]["_id"] == "sess-1"
    assert set(call["filter"]["expires_at"]) == {"$lte"}
    assert call["upsert"] is True
    assert call["update"]["$set"]["doctor_id"] == "doc-a"
    assert call["update"]["$set"]["worker"] == leases._WORKER_ID


async def test_a_live_lease_refuses_the_second_acquire(col):
    """A duplicate _id is Mongo telling us another socket already holds this session."""
    col.raise_duplicate = True
    assert await leases.acquire("sess-1", "doc-b") is False


async def test_expiry_is_ttl_seconds_ahead(col, monkeypatch):
    monkeypatch.setattr(settings, "CABIN_LEASE_TTL_SECS", 120)
    before = datetime.utcnow()
    await leases.acquire("sess-1", "doc-a")
    expires = col.update_filters[0]["update"]["$set"]["expires_at"]
    assert timedelta(seconds=119) <= (expires - before) <= timedelta(seconds=121)


# ── renew ─────────────────────────────────────────────────────────────────


async def test_renew_matches_only_this_worker(col):
    """A lease already taken over by another worker must not be resurrected."""
    assert await leases.renew("sess-1") is True
    assert col.update_filters[0]["filter"] == {
        "_id": "sess-1",
        "worker": leases._WORKER_ID,
    }


async def test_renew_returns_false_when_the_lease_was_taken_over(col):
    col.matched = 0
    assert await leases.renew("sess-1") is False


# ── release ───────────────────────────────────────────────────────────────


async def test_release_deletes_only_this_workers_lease(col):
    await leases.acquire("sess-1", "doc-a")
    await leases.release("sess-1")
    assert col.delete_filters[0] == {"_id": "sess-1", "worker": leases._WORKER_ID}
    assert "sess-1" not in leases._mem_active


# ── active_count ──────────────────────────────────────────────────────────


async def test_active_count_ignores_expired_leases(col):
    col.count = 2
    assert await leases.active_count("doc-a") == 2
    flt = col.count_filters[0]
    assert flt["doctor_id"] == "doc-a"
    assert set(flt["expires_at"]) == {"$gt"}


# ── fail-open contract ────────────────────────────────────────────────────


async def test_acquire_fails_open_when_mongo_is_down():
    """Locking a doctor out of their own consultation is worse than the duplicate
    connection the lease exists to prevent. Degrades to the per-process guard."""
    assert await leases.acquire("sess-1", "doc-a") is True
    assert await leases.acquire("sess-1", "doc-a") is False, "per-process guard is gone"
    assert await leases.acquire("sess-2", "doc-a") is True


async def test_release_frees_the_degraded_guard():
    await leases.acquire("sess-1", "doc-a")
    await leases.release("sess-1")
    assert await leases.acquire("sess-1", "doc-a") is True


async def test_active_count_falls_back_to_this_worker():
    await leases.acquire("sess-1", "doc-a")
    await leases.acquire("sess-2", "doc-a")
    await leases.acquire("sess-3", "doc-b")
    assert await leases.active_count("doc-a") == 2
    assert await leases.active_count("doc-b") == 1
    assert await leases.active_count("doc-c") == 0


async def test_renew_does_not_raise_when_mongo_is_down():
    assert await leases.renew("sess-1") is False
