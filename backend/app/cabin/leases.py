"""Cross-worker cabin session leases.

The duplicate-connection guard has to hold across uvicorn workers: two sockets on one
session_id open two ElevenLabs consults and double-bill them. There is no Redis in this
project, so the lease is a Mongo document keyed by session_id, renewed by the running
session and reclaimable at its expiry when a worker dies mid-consult.

Every call fails *open*. If Mongo is unavailable, acquire() returns True and
active_count() returns 0, so the feature degrades to exactly the per-process guard that
existed before this module rather than locking doctors out of their own consultations.

Unlike store.py this deliberately has no permanent failure latch. That latch exists
there because update() runs every 15s per session on a hot path; lease calls are two per
session plus one renewal per 20s, and a latch on a *safety* mechanism would keep
cross-worker protection off until the process restarts, long after Mongo recovered.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta

from pymongo.errors import DuplicateKeyError

from app.core.config import settings

log = logging.getLogger(__name__)

# Identifies this process as a lease holder, so a renewal cannot resurrect a lease that
# another worker has already taken over.
_WORKER_ID = uuid.uuid4().hex

# Degraded fallback, used only when Mongo is unreachable: session_id -> doctor_id.
_mem_active: dict[str, str] = {}


def _col():
    from app.core.database import get_db

    return get_db()["cabin_leases"]


def _expiry(now: datetime) -> datetime:
    return now + timedelta(seconds=settings.CABIN_LEASE_TTL_SECS)


async def acquire(session_id: str, doctor_id: str) -> bool:
    """Take the lease for a session. False means someone else holds a live one.

    The session_id is the document _id, so the uniqueness that decides the race is
    enforced by the primary key. A conditional upsert filtered on an elapsed expires_at
    means: insert when absent, take over when expired, and raise DuplicateKeyError when
    a live lease exists. One atomic server-side operation, no read-then-write window.
    """
    now = datetime.utcnow()
    try:
        await _col().update_one(
            {"_id": session_id, "expires_at": {"$lte": now}},
            {
                "$set": {
                    "doctor_id": doctor_id,
                    "worker": _WORKER_ID,
                    "acquired_at": now,
                    "expires_at": _expiry(now),
                }
            },
            upsert=True,
        )
    except DuplicateKeyError:
        return False
    except Exception as exc:
        log.warning("Cabin lease store unavailable, using per-process guard: %s", exc)
        if session_id in _mem_active:
            return False
        _mem_active[session_id] = doctor_id
        return True
    _mem_active[session_id] = doctor_id
    return True


async def renew(session_id: str) -> bool:
    """Push the expiry out. Matching on worker means a lease already taken over by
    another worker is not resurrected."""
    now = datetime.utcnow()
    try:
        result = await _col().update_one(
            {"_id": session_id, "worker": _WORKER_ID},
            {"$set": {"expires_at": _expiry(now)}},
        )
    except Exception as exc:
        log.warning("Cabin lease renewal failed for %s: %s", session_id, exc)
        return False
    return result.matched_count == 1


async def release(session_id: str) -> None:
    _mem_active.pop(session_id, None)
    try:
        await _col().delete_one({"_id": session_id, "worker": _WORKER_ID})
    except Exception as exc:
        # The TTL is the backstop; a stuck lease expires on its own.
        log.warning("Cabin lease release failed for %s: %s", session_id, exc)


async def active_count(doctor_id: str) -> int:
    """How many live consultations this doctor currently holds."""
    now = datetime.utcnow()
    try:
        return await _col().count_documents(
            {"doctor_id": doctor_id, "expires_at": {"$gt": now}}
        )
    except Exception as exc:
        log.warning("Cabin lease count unavailable, counting this worker only: %s", exc)
        return sum(1 for held in _mem_active.values() if held == doctor_id)
