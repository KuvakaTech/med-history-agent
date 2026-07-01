"""Session store: MongoDB-backed with automatic in-memory fallback for local dev."""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

from app.clinical.context import ConsultationContext

log = logging.getLogger(__name__)

# In-process cache — used as write-through copy and fallback when MongoDB is down.
# _mongo_write_failed latches True after any write error so we stop retrying writes.
# For READS we always try MongoDB first regardless of latch state, so sessions
# saved to MongoDB before a transient write error are still discoverable.
_mem: dict[str, dict] = {}
_mongo_write_failed = False


def _col():
    from app.core.database import get_db
    return get_db()["sessions"]


class SessionStore:
    async def create(self, ctx: ConsultationContext, user_id: Optional[str] = None) -> ConsultationContext:
        global _mongo_write_failed
        doc = ctx.model_dump(mode="json")
        if user_id:
            doc["user_id"] = user_id
        # Always keep a local copy as fallback
        _mem[ctx.session_id] = doc
        if _mongo_write_failed:
            return ctx
        try:
            await _col().insert_one(doc)
        except Exception as exc:
            log.warning("MongoDB write unavailable — session kept in memory: %s", exc)
            _mongo_write_failed = True
        return ctx

    async def get(self, session_id: str, user_id: Optional[str] = None) -> Optional[ConsultationContext]:
        query: dict = {"session_id": session_id}
        if user_id:
            query["user_id"] = user_id

        # Always try MongoDB first — session may have been saved there even if
        # writes later failed (do not skip based on _mongo_write_failed).
        try:
            doc = await _col().find_one(query, {"_id": 0})
            if doc is not None:
                return ConsultationContext.model_validate(doc)
            # Not in MongoDB — fall through to check local cache
        except Exception as exc:
            log.warning("MongoDB read failed, checking local cache: %s", exc)

        # In-memory fallback
        doc = _mem.get(session_id)
        if doc is None:
            return None
        if user_id and doc.get("user_id") != user_id:
            return None
        return ConsultationContext.model_validate(doc)

    async def update(self, ctx: ConsultationContext) -> ConsultationContext:
        global _mongo_write_failed
        ctx.updated_at = datetime.utcnow()
        doc = ctx.model_dump(mode="json")
        # Update local copy while preserving server-side fields (user_id) not in the model
        if ctx.session_id in _mem:
            preserved = {k: v for k, v in _mem[ctx.session_id].items() if k not in doc}
            _mem[ctx.session_id] = {**doc, **preserved}
        if _mongo_write_failed:
            return ctx
        try:
            # $set updates only ConsultationContext fields — user_id stays untouched in MongoDB
            await _col().update_one(
                {"session_id": ctx.session_id},
                {"$set": doc},
                upsert=True,
            )
        except Exception as exc:
            log.warning("MongoDB update failed, using local cache: %s", exc)
            _mongo_write_failed = True
            if ctx.session_id in _mem:
                preserved = {k: v for k, v in _mem[ctx.session_id].items() if k not in doc}
                _mem[ctx.session_id] = {**doc, **preserved}
            else:
                _mem[ctx.session_id] = doc
        return ctx

    async def delete(self, session_id: str) -> None:
        _mem.pop(session_id, None)
        try:
            await _col().delete_one({"session_id": session_id})
        except Exception:
            pass

    async def list_sessions(self) -> list[str]:
        try:
            cursor = _col().find({}, {"session_id": 1, "_id": 0})
            return [d["session_id"] async for d in cursor]
        except Exception:
            return list(_mem.keys())

    async def list_for_patient(self, patient_id: str, doctor_id: str) -> list[dict]:
        _proj = {
            "_id": 0, "session_id": 1, "specialty": 1, "created_at": 1,
            "current_stage": 1, "chief_complaint": 1, "patient_name": 1,
            "summary": 1, "diagnosis": 1, "prescription": 1,
        }
        try:
            cursor = _col().find(
                {"patient_id": patient_id, "user_id": doctor_id}, _proj
            ).sort("created_at", -1)
            return [doc async for doc in cursor]
        except Exception as exc:
            log.warning("list_for_patient failed: %s", exc)
            return [
                {k: v for k, v in doc.items() if k in _proj}
                for doc in _mem.values()
                if doc.get("patient_id") == patient_id and doc.get("user_id") == doctor_id
            ]


session_store = SessionStore()
