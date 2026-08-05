"""Shared fixtures. Cabin tests never touch a real MongoDB, ElevenLabs socket, or LLM —
every external edge is faked so the suite runs offline and deterministically."""

from __future__ import annotations

import os

import pytest

# Settings are read at import time, so a JWT secret has to exist before app.core.config
# is first imported. setdefault keeps a real .env value if one is already present.
os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-for-pytest-only")

from app.cabin import leases as cabin_leases  # noqa: E402
from app.cabin import store as cabin_store  # noqa: E402


@pytest.fixture(autouse=True)
def isolate_cabin_leases(monkeypatch):
    """Same reasoning as isolate_cabin_store: no test may reach a real MongoDB, and the
    collection accessor fails fast so reads don't wait out the 5s server-selection
    timeout. Leases fail open, so this leaves the per-process guard in play."""

    def unavailable():
        raise RuntimeError("MongoDB intentionally unavailable in tests")

    monkeypatch.setattr(cabin_leases, "_col", unavailable)
    cabin_leases._mem_active.clear()
    yield
    cabin_leases._mem_active.clear()


@pytest.fixture(autouse=True)
def isolate_cabin_store(monkeypatch):
    """Force the in-memory fallback path and clear it between tests, so no test
    depends on (or pollutes) a real database.

    Reads deliberately try MongoDB first in production (a session written before a
    transient write error must stay discoverable), so the collection accessor is
    stubbed to fail fast here — otherwise every read waits out the 5s server-selection
    timeout and the suite crawls.
    """

    def unavailable():
        raise RuntimeError("MongoDB intentionally unavailable in tests")

    monkeypatch.setattr(cabin_store, "_col", unavailable)
    cabin_store._mem.clear()
    cabin_store._mongo_write_failed = True
    yield
    cabin_store._mem.clear()
    cabin_store._mongo_write_failed = False
