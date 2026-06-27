"""Session store: MongoDB-backed with automatic in-memory fallback for local dev."""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

from app.clinical.context import ConsultationContext

log = logging.getLogger(__name__)

# In-process fallback used when MongoDB is unavailable
_mem: dict[str, dict] = {}
_mongo_failed = False  # latched True on first MongoDB error


def _col():
    from app.core.database import get_db
    return get_db()["sessions"]


class SessionStore:
    async def create(self, ctx: ConsultationContext) -> ConsultationContext:
        global _mongo_failed
        if _mongo_failed:
            _mem[ctx.session_id] = ctx.model_dump(mode="json")
            return ctx
        try:
            doc = ctx.model_dump(mode="json")
            await _col().insert_one(doc)
            return ctx
        except Exception as exc:
            log.warning("MongoDB unavailable — switching to in-memory store: %s", exc)
            _mongo_failed = True
            _mem[ctx.session_id] = ctx.model_dump(mode="json")
            return ctx

    async def get(self, session_id: str) -> Optional[ConsultationContext]:
        if _mongo_failed:
            doc = _mem.get(session_id)
            return ConsultationContext.model_validate(doc) if doc else None
        try:
            doc = await _col().find_one({"session_id": session_id}, {"_id": 0})
            return ConsultationContext.model_validate(doc) if doc else None
        except Exception as exc:
            log.warning("MongoDB read failed, falling back to memory: %s", exc)
            doc = _mem.get(session_id)
            return ConsultationContext.model_validate(doc) if doc else None

    async def update(self, ctx: ConsultationContext) -> ConsultationContext:
        global _mongo_failed
        ctx.updated_at = datetime.utcnow()
        if _mongo_failed:
            _mem[ctx.session_id] = ctx.model_dump(mode="json")
            return ctx
        try:
            doc = ctx.model_dump(mode="json")
            await _col().replace_one({"session_id": ctx.session_id}, doc, upsert=True)
            return ctx
        except Exception as exc:
            log.warning("MongoDB update failed, falling back to memory: %s", exc)
            _mongo_failed = True
            _mem[ctx.session_id] = ctx.model_dump(mode="json")
            return ctx

    async def delete(self, session_id: str) -> None:
        _mem.pop(session_id, None)
        if not _mongo_failed:
            try:
                await _col().delete_one({"session_id": session_id})
            except Exception:
                pass

    async def list_sessions(self) -> list[str]:
        if _mongo_failed:
            return list(_mem.keys())
        try:
            cursor = _col().find({}, {"session_id": 1, "_id": 0})
            return [d["session_id"] async for d in cursor]
        except Exception:
            return list(_mem.keys())


session_store = SessionStore()
