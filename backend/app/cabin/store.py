"""Cabin session store: MongoDB-backed with automatic in-memory fallback.

Structural copy of app/clinical/session_store.py, with its own module-global
latch — a cabin write failure must not stop questionnaire session writes.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

from app.cabin.models import CabinSession

log = logging.getLogger(__name__)

_mem: dict[str, dict] = {}
_mongo_write_failed = False

# Summary fields for list views. `panel` is included because the whole point of a list is
# to show what each consultation was about; `utterances` and `suggestions` are not.
_LIST_PROJECTION = {
    "_id": 0,
    "session_id": 1,
    "doctor_id": 1,
    "patient_id": 1,
    "patient_name": 1,
    "specialty": 1,
    "status": 1,
    "workflow": 1,
    "created_at": 1,
    "ended_at": 1,
    "panel": 1,
}


def _col():
    from app.core.database import get_db

    return get_db()["cabin_sessions"]


class CabinSessionStore:
    async def create(self, session: CabinSession) -> CabinSession:
        global _mongo_write_failed
        doc = session.model_dump(mode="json")
        _mem[session.session_id] = doc
        if _mongo_write_failed:
            return session
        try:
            await _col().insert_one(doc)
        except Exception as exc:
            log.warning(
                "MongoDB write unavailable — cabin session kept in memory: %s", exc
            )
            _mongo_write_failed = True
        return session

    async def get(
        self, session_id: str, doctor_id: Optional[str] = None
    ) -> Optional[CabinSession]:
        query: dict = {"session_id": session_id}
        if doctor_id:
            query["doctor_id"] = doctor_id

        try:
            doc = await _col().find_one(query, {"_id": 0})
            if doc is not None:
                return CabinSession.model_validate(doc)
        except Exception as exc:
            log.warning("MongoDB read failed, checking local cache: %s", exc)

        doc = _mem.get(session_id)
        if doc is None:
            return None
        if doctor_id and doc.get("doctor_id") != doctor_id:
            return None
        return CabinSession.model_validate(doc)

    async def update(self, session: CabinSession) -> CabinSession:
        global _mongo_write_failed
        session.updated_at = datetime.utcnow()
        doc = session.model_dump(mode="json")
        _mem[session.session_id] = doc
        if _mongo_write_failed:
            return session
        try:
            await _col().update_one(
                {"session_id": session.session_id},
                {"$set": doc},
                upsert=True,
            )
        except Exception as exc:
            log.warning("MongoDB update failed, using local cache: %s", exc)
            _mongo_write_failed = True
        return session

    async def delete(self, session_id: str) -> None:
        _mem.pop(session_id, None)
        try:
            await _col().delete_one({"session_id": session_id})
        except Exception:
            pass

    async def _list(self, query: dict, limit: int) -> list[dict]:
        """Summary projection shared by the list views. Utterances and suggestions are
        deliberately excluded — a list must not ship a 90-minute transcript per row."""
        try:
            cursor = (
                _col().find(query, _LIST_PROJECTION).sort("created_at", -1).limit(limit)
            )
            return [doc async for doc in cursor]
        except Exception as exc:
            log.warning("Cabin list failed, using local cache: %s", exc)
            rows = [
                {k: v for k, v in doc.items() if k in _LIST_PROJECTION}
                for doc in _mem.values()
                if all(doc.get(k) == v for k, v in query.items())
            ]
            rows.sort(key=lambda d: d.get("created_at") or "", reverse=True)
            return rows[:limit]

    async def list_for_doctor(self, doctor_id: str, limit: int = 50) -> list[dict]:
        return await self._list({"doctor_id": doctor_id}, limit)

    async def list_for_patient(
        self, patient_id: str, doctor_id: str, limit: int = 50
    ) -> list[dict]:
        """Prior consultations for one patient — the input to the profile builder."""
        return await self._list(
            {"patient_id": patient_id, "doctor_id": doctor_id}, limit
        )


cabin_session_store = CabinSessionStore()
