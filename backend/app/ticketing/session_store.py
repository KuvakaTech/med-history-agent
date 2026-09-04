"""TicketSession store — MongoDB-backed with in-memory fallback.

ticket_number: auto-incremented human-readable ID, e.g. "TKT-000042".
Generated atomically using a Mongo counter document. Falls back to a
timestamp-based ID if Mongo is unavailable.

Stale sweep: sessions with status="active" and updated_at older than
STALE_MINUTES are lazily flipped to "partial" on read/list.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Optional

from app.ticketing.models import TicketSession

log = logging.getLogger(__name__)

_mem: dict[str, dict] = {}
_mem_by_ticket: dict[str, str] = {}   # ticket_number → session_id
_mongo_write_failed = False
_local_counter = 0   # fallback counter when Mongo is down
_local_opd: dict[str, int] = {}  # hospital_id_YYYYMMDD → seq


def _ist_date_key() -> str:
    """IST calendar date used to reset the daily OPD sequence."""
    now = datetime.utcnow() + timedelta(hours=5.5)
    return now.strftime("%Y%m%d")

STALE_MINUTES = 30

_LIST_PROJECTION = {
    "_id": 0,
    "session_id": 1,
    "ticket_number": 1,
    "hospital_id": 1,
    "patient_id": 1,
    "phase": 1,
    "status": 1,
    "category": 1,
    "language": 1,
    "gender": 1,
    "caste": 1,
    "opd_number": 1,
    "address": 1,
    "guardian_name": 1,
    "turn_count": 1,
    "started_at": 1,
    "ended_at": 1,
    "updated_at": 1,
    "deleted_at": 1,
    "flags": 1,
}


def _col():
    from app.core.database import get_db
    return get_db()["ticket_sessions"]


def _counters_col():
    from app.core.database import get_db
    return get_db()["ticket_counters"]


def _is_stale(doc: dict) -> bool:
    if doc.get("status") != "active":
        return False
    ts = doc.get("updated_at") or doc.get("started_at")
    if not ts:
        return False
    if isinstance(ts, str):
        try:
            ts = datetime.fromisoformat(ts)
        except Exception:
            return False
    return (datetime.utcnow() - ts) > timedelta(minutes=STALE_MINUTES)


async def _next_ticket_number() -> str:
    """Atomically increment the global ticket counter and return formatted string."""
    global _local_counter
    try:
        result = await _counters_col().find_one_and_update(
            {"_id": "ticket_number"},
            {"$inc": {"seq": 1}},
            upsert=True,
            return_document=True,
        )
        seq: int = result["seq"]
    except Exception as exc:
        log.warning("Ticket counter unavailable, using local fallback: %s", exc)
        _local_counter += 1
        seq = _local_counter
    return f"TKT-{seq:06d}"


async def _next_opd_number(hospital_id: str, date_key: Optional[str] = None) -> int:
    """Increment the per-hospital IST-day OPD sequence. Resets to 1 each new date."""
    date_part = date_key or _ist_date_key()
    counter_id = f"opd_{hospital_id}_{date_part}"
    try:
        result = await _counters_col().find_one_and_update(
            {"_id": counter_id},
            {"$inc": {"seq": 1}},
            upsert=True,
            return_document=True,
        )
        return int(result["seq"])
    except Exception as exc:
        log.warning("OPD counter unavailable, using local fallback: %s", exc)
        _local_opd[counter_id] = _local_opd.get(counter_id, 0) + 1
        return _local_opd[counter_id]


class TicketSessionStore:
    async def create(self, session: TicketSession) -> TicketSession:
        global _mongo_write_failed
        # Assign ticket number before first persist
        session.ticket_number = await _next_ticket_number()
        session.opd_number = await _next_opd_number(session.hospital_id)
        doc = session.model_dump(mode="json")
        _mem[session.session_id] = doc
        if session.ticket_number:
            _mem_by_ticket[session.ticket_number] = session.session_id
        if not _mongo_write_failed:
            try:
                await _col().insert_one(dict(doc))
            except Exception as exc:
                log.warning("TicketSession create failed: %s", exc)
                _mongo_write_failed = True
        return session

    async def get(
        self, session_id: str, hospital_id: Optional[str] = None
    ) -> Optional[TicketSession]:
        query: dict = {"session_id": session_id}
        if hospital_id:
            query["hospital_id"] = hospital_id
        try:
            doc = await _col().find_one(query, {"_id": 0})
            if doc:
                doc = await self._maybe_flip_stale(doc)
                return TicketSession.model_validate(doc)
        except Exception as exc:
            log.warning("TicketSession get failed: %s", exc)

        doc = _mem.get(session_id)
        if doc is None:
            return None
        if hospital_id and doc.get("hospital_id") != hospital_id:
            return None
        doc = await self._maybe_flip_stale(doc)
        return TicketSession.model_validate(doc)

    async def get_by_ticket_number(
        self, ticket_number: str, hospital_id: Optional[str] = None
    ) -> Optional[TicketSession]:
        """Lookup by human-readable ticket number — used by admin search."""
        query: dict = {"ticket_number": ticket_number}
        if hospital_id:
            query["hospital_id"] = hospital_id
        try:
            doc = await _col().find_one(query, {"_id": 0})
            if doc:
                return TicketSession.model_validate(doc)
        except Exception as exc:
            log.warning("get_by_ticket_number failed: %s", exc)
        sid = _mem_by_ticket.get(ticket_number)
        if sid:
            return await self.get(sid, hospital_id=hospital_id)
        return None

    async def update(self, session: TicketSession) -> TicketSession:
        global _mongo_write_failed
        session.updated_at = datetime.utcnow()
        doc = session.model_dump(mode="json")
        _mem[session.session_id] = doc
        if session.ticket_number:
            _mem_by_ticket[session.ticket_number] = session.session_id
        if not _mongo_write_failed:
            try:
                await _col().update_one(
                    {"session_id": session.session_id},
                    {"$set": doc},
                    upsert=True,
                )
            except Exception as exc:
                log.warning("TicketSession update failed: %s", exc)
                _mongo_write_failed = True
        return session

    async def soft_delete(self, session_id: str, hospital_id: str) -> bool:
        global _mongo_write_failed
        now = datetime.utcnow()
        doc = _mem.get(session_id)
        if doc and doc.get("hospital_id") == hospital_id:
            doc["deleted_at"] = now.isoformat()
        if not _mongo_write_failed:
            try:
                result = await _col().update_one(
                    {"session_id": session_id, "hospital_id": hospital_id},
                    {"$set": {"deleted_at": now}},
                )
                return result.matched_count > 0
            except Exception as exc:
                log.warning("TicketSession soft_delete failed: %s", exc)
        return doc is not None and doc.get("hospital_id") == hospital_id

    async def list_for_hospital(
        self,
        hospital_id: str,
        limit: int = 100,
        status: Optional[str] = None,
        category_key: Optional[str] = None,
        include_deleted: bool = False,
        search_ticket: Optional[str] = None,
    ) -> list[dict]:
        query: dict = {"hospital_id": hospital_id}
        if status:
            query["status"] = status
        if category_key:
            query["category.key"] = category_key
        if not include_deleted:
            query["deleted_at"] = None
        if search_ticket:
            query["ticket_number"] = search_ticket.upper()
        try:
            cursor = (
                _col()
                .find(query, _LIST_PROJECTION)
                .sort("started_at", -1)
                .limit(limit)
            )
            return [doc async for doc in cursor]
        except Exception as exc:
            log.warning("TicketSession list failed, using cache: %s", exc)

        rows = [
            {k: v for k, v in d.items() if k in _LIST_PROJECTION}
            for d in _mem.values()
            if d.get("hospital_id") == hospital_id
            and (not status or d.get("status") == status)
            and (not category_key or (d.get("category") or {}).get("key") == category_key)
            and (include_deleted or d.get("deleted_at") is None)
            and (not search_ticket or d.get("ticket_number") == search_ticket.upper())
        ]
        rows.sort(key=lambda d: d.get("started_at") or "", reverse=True)
        return rows[:limit]

    async def list_for_patient(
        self, patient_id: str, hospital_id: Optional[str] = None, include_deleted: bool = False
    ) -> list[dict]:
        query: dict = {"patient_id": patient_id}
        if hospital_id:
            query["hospital_id"] = hospital_id
        if not include_deleted:
            query["deleted_at"] = None
        try:
            cursor = (
                _col()
                .find(query, _LIST_PROJECTION)
                .sort("started_at", -1)
                .limit(20)
            )
            return [doc async for doc in cursor]
        except Exception as exc:
            log.warning("TicketSession list_for_patient failed: %s", exc)
        return [
            {k: v for k, v in d.items() if k in _LIST_PROJECTION}
            for d in _mem.values()
            if d.get("patient_id") == patient_id
            and (not hospital_id or d.get("hospital_id") == hospital_id)
            and (include_deleted or d.get("deleted_at") is None)
        ]

    async def _maybe_flip_stale(self, doc: dict) -> dict:
        if not _is_stale(doc):
            return doc
        doc["status"] = "partial"
        sid = doc.get("session_id")
        if sid:
            if sid in _mem:
                _mem[sid]["status"] = "partial"
            try:
                await _col().update_one(
                    {"session_id": sid}, {"$set": {"status": "partial"}}
                )
            except Exception:
                pass
        return doc


ticket_session_store = TicketSessionStore()
