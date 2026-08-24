"""Hospital store — MongoDB-backed with in-memory fallback."""
from __future__ import annotations

import logging
from typing import Optional

from app.ticketing.models import Hospital, TicketCategory, DEFAULT_CATEGORIES

log = logging.getLogger(__name__)

_mem_hospitals: dict[str, dict] = {}
_mem_categories: dict[str, dict] = {}  # category_id -> doc
_mongo_write_failed = False


def _hospitals_col():
    from app.core.database import get_db
    return get_db()["ticket_hospitals"]


def _categories_col():
    from app.core.database import get_db
    return get_db()["ticket_categories"]


class HospitalStore:
    async def create(self, hospital: Hospital) -> Hospital:
        global _mongo_write_failed
        doc = hospital.model_dump(mode="json")
        _mem_hospitals[hospital.hospital_id] = doc
        if not _mongo_write_failed:
            try:
                await _hospitals_col().insert_one(dict(doc))
            except Exception as exc:
                log.warning("Hospital MongoDB write failed: %s", exc)
                _mongo_write_failed = True

        # Seed default categories
        for key, label in DEFAULT_CATEGORIES:
            cat = TicketCategory(
                hospital_id=hospital.hospital_id,
                key=key,
                label=label,
                active=True,
            )
            await self.create_category(cat)

        return hospital

    async def get_by_slug(self, slug: str) -> Optional[Hospital]:
        try:
            doc = await _hospitals_col().find_one({"slug": slug}, {"_id": 0})
            if doc:
                return Hospital.model_validate(doc)
        except Exception as exc:
            log.warning("Hospital read failed: %s", exc)

        for doc in _mem_hospitals.values():
            if doc.get("slug") == slug:
                return Hospital.model_validate(doc)
        return None

    async def get(self, hospital_id: str) -> Optional[Hospital]:
        try:
            doc = await _hospitals_col().find_one(
                {"hospital_id": hospital_id}, {"_id": 0}
            )
            if doc:
                return Hospital.model_validate(doc)
        except Exception as exc:
            log.warning("Hospital read failed: %s", exc)

        doc = _mem_hospitals.get(hospital_id)
        return Hospital.model_validate(doc) if doc else None

    async def list_all(self) -> list[dict]:
        try:
            cursor = _hospitals_col().find({}, {"_id": 0})
            return [doc async for doc in cursor]
        except Exception:
            return list(_mem_hospitals.values())

    # ── Categories ────────────────────────────────────────────

    async def create_category(self, cat: TicketCategory) -> TicketCategory:
        global _mongo_write_failed
        doc = cat.model_dump(mode="json")
        _mem_categories[cat.category_id] = doc
        if not _mongo_write_failed:
            try:
                await _categories_col().insert_one(dict(doc))
            except Exception as exc:
                log.warning("Category write failed: %s", exc)
        return cat

    async def list_categories(
        self, hospital_id: str, active_only: bool = True
    ) -> list[TicketCategory]:
        query: dict = {"hospital_id": hospital_id}
        if active_only:
            query["active"] = True
        try:
            cursor = _categories_col().find(query, {"_id": 0})
            docs = [doc async for doc in cursor]
            if docs:
                return [TicketCategory.model_validate(d) for d in docs]
        except Exception as exc:
            log.warning("Category list failed, using cache: %s", exc)

        return [
            TicketCategory.model_validate(d)
            for d in _mem_categories.values()
            if d.get("hospital_id") == hospital_id
            and (not active_only or d.get("active"))
        ]

    async def update_category(
        self, category_id: str, hospital_id: str, **fields
    ) -> Optional[TicketCategory]:
        global _mongo_write_failed
        doc = _mem_categories.get(category_id)
        if doc and doc.get("hospital_id") != hospital_id:
            return None
        try:
            result = await _categories_col().find_one_and_update(
                {"category_id": category_id, "hospital_id": hospital_id},
                {"$set": fields},
                return_document=True,
                projection={"_id": 0},
            )
            if result:
                _mem_categories[category_id] = result
                return TicketCategory.model_validate(result)
        except Exception as exc:
            log.warning("Category update failed: %s", exc)
            _mongo_write_failed = True
        if doc:
            doc.update(fields)
            return TicketCategory.model_validate(doc)
        return None


hospital_store = HospitalStore()
