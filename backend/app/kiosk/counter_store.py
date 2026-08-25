"""Daily complaint number counter — JS-VNS-YYYYMMDD-NNNNN."""
from __future__ import annotations

import logging
from datetime import datetime, timezone

log = logging.getLogger(__name__)

_local_counters: dict[str, int] = {}
_mongo_write_failed = False


def _col():
    from app.core.database import get_db
    return get_db()["kiosk_counters"]


def _date_key() -> str:
    # IST calendar date for complaint numbers
    from datetime import timedelta

    now = datetime.now(timezone.utc) + timedelta(hours=5.5)
    return now.strftime("%Y%m%d")


async def next_complaint_number(centre_id: str, prefix: str = "JS-VNS") -> str:
    """Return {prefix}-YYYYMMDD-NNNNN for this centre and IST day."""
    global _mongo_write_failed
    date_part = _date_key()
    counter_id = f"{centre_id}_{date_part}"
    seq = 0
    try:
        result = await _col().find_one_and_update(
            {"_id": counter_id},
            {"$inc": {"seq": 1}},
            upsert=True,
            return_document=True,
        )
        seq = int(result["seq"])
    except Exception as exc:
        log.warning("Kiosk counter unavailable, using local fallback: %s", exc)
        _mongo_write_failed = True
        key = counter_id
        _local_counters[key] = _local_counters.get(key, 0) + 1
        seq = _local_counters[key]
    return f"{prefix}-{date_part}-{seq:05d}"
