"""Kiosk centre store — MongoDB-backed with in-memory fallback."""
from __future__ import annotations

import logging
from typing import Optional

from app.kiosk.models import KioskCentre

log = logging.getLogger(__name__)

_mem_centres: dict[str, dict] = {}
_mongo_write_failed = False


def _col():
    from app.core.database import get_db
    return get_db()["kiosk_centres"]


class CentreStore:
    async def create(self, centre: KioskCentre) -> KioskCentre:
        global _mongo_write_failed
        doc = centre.model_dump(mode="json")
        _mem_centres[centre.centre_id] = doc
        if not _mongo_write_failed:
            try:
                await _col().insert_one(dict(doc))
            except Exception as exc:
                log.warning("Kiosk centre MongoDB write failed: %s", exc)
                _mongo_write_failed = True
        return centre

    async def get_by_slug(self, slug: str) -> Optional[KioskCentre]:
        try:
            doc = await _col().find_one({"slug": slug}, {"_id": 0})
            if doc:
                return KioskCentre.model_validate(doc)
        except Exception as exc:
            log.warning("Kiosk centre read failed: %s", exc)
        for doc in _mem_centres.values():
            if doc.get("slug") == slug:
                return KioskCentre.model_validate(doc)
        return None

    async def get(self, centre_id: str) -> Optional[KioskCentre]:
        try:
            doc = await _col().find_one({"centre_id": centre_id}, {"_id": 0})
            if doc:
                return KioskCentre.model_validate(doc)
        except Exception as exc:
            log.warning("Kiosk centre get failed: %s", exc)
        doc = _mem_centres.get(centre_id)
        return KioskCentre.model_validate(doc) if doc else None

    async def list_all(self) -> list[dict]:
        try:
            cursor = _col().find({}, {"_id": 0})
            return [doc async for doc in cursor]
        except Exception:
            return list(_mem_centres.values())


centre_store = CentreStore()
