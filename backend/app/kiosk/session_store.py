"""Kiosk session store — MongoDB-backed with in-memory fallback."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Optional

from app.kiosk.models import KioskSession

log = logging.getLogger(__name__)

_mem: dict[str, dict] = {}
_mem_by_complaint: dict[str, str] = {}
_mongo_write_failed = False

STALE_MINUTES = 30


def _col():
    from app.core.database import get_db
    return get_db()["kiosk_sessions"]


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


def _mongo_doc(session: KioskSession) -> dict:
    """Mongo payload — omit null fields so sparse/partial unique indexes work."""
    return session.model_dump(mode="json", exclude_none=True)


class KioskSessionStore:
    async def create(self, session: KioskSession) -> KioskSession:
        global _mongo_write_failed
        doc = session.model_dump(mode="json")
        _mem[session.session_id] = doc
        if not _mongo_write_failed:
            try:
                await _col().insert_one(_mongo_doc(session))
            except Exception as exc:
                log.error("KioskSession create failed: %s", exc, exc_info=True)
                _mongo_write_failed = True
        return session

    async def get(
        self, session_id: str, centre_id: Optional[str] = None
    ) -> Optional[KioskSession]:
        query: dict = {"session_id": session_id}
        if centre_id:
            query["centre_id"] = centre_id
        try:
            doc = await _col().find_one(query, {"_id": 0})
            if doc:
                doc = await self._maybe_flip_stale(doc)
                return KioskSession.model_validate(doc)
        except Exception as exc:
            log.warning("KioskSession get failed: %s", exc)
        doc = _mem.get(session_id)
        if doc is None:
            return None
        if centre_id and doc.get("centre_id") != centre_id:
            return None
        doc = await self._maybe_flip_stale(doc)
        return KioskSession.model_validate(doc)

    async def update(self, session: KioskSession) -> KioskSession:
        global _mongo_write_failed
        session.updated_at = datetime.utcnow()
        doc = session.model_dump(mode="json")
        _mem[session.session_id] = doc
        if session.complaint_number:
            _mem_by_complaint[session.complaint_number] = session.session_id
        if not _mongo_write_failed:
            try:
                await _col().update_one(
                    {"session_id": session.session_id},
                    {"$set": _mongo_doc(session)},
                    upsert=True,
                )
            except Exception as exc:
                log.error("KioskSession update failed: %s", exc, exc_info=True)
                _mongo_write_failed = True
        return session

    async def soft_delete(self, session_id: str, centre_id: str) -> bool:
        global _mongo_write_failed
        now = datetime.utcnow()
        doc = _mem.get(session_id)
        if doc and doc.get("centre_id") == centre_id:
            doc["deleted_at"] = now.isoformat()
        if not _mongo_write_failed:
            try:
                result = await _col().update_one(
                    {"session_id": session_id, "centre_id": centre_id},
                    {"$set": {"deleted_at": now}},
                )
                return result.matched_count > 0
            except Exception as exc:
                log.warning("KioskSession soft_delete failed: %s", exc)
        return doc is not None and doc.get("centre_id") == centre_id

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


kiosk_session_store = KioskSessionStore()
