"""MongoDB-backed refresh token store with rotation and revocation support."""
import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

from app.core.database import get_db


def _hash(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def generate() -> str:
    return secrets.token_hex(32)


async def store(raw_token: str, expire_days: int, user_id: Optional[str] = None) -> None:
    db = get_db()
    doc = {
        "token_hash": _hash(raw_token),
        "expires_at": datetime.now(timezone.utc) + timedelta(days=expire_days),
        "revoked": False,
        "created_at": datetime.now(timezone.utc),
    }
    if user_id:
        doc["user_id"] = user_id
    await db["refresh_tokens"].insert_one(doc)


async def rotate(old_raw: str, new_raw: str, expire_days: int) -> Optional[str]:
    """Revoke old token, store new one. Returns user_id or None if old token is invalid."""
    db = get_db()
    result = await db["refresh_tokens"].find_one_and_update(
        {
            "token_hash": _hash(old_raw),
            "revoked": False,
            "expires_at": {"$gt": datetime.now(timezone.utc)},
        },
        {"$set": {"revoked": True}},
    )
    if result is None:
        return None
    user_id = result.get("user_id")
    await store(new_raw, expire_days, user_id=user_id)
    return user_id


async def revoke(raw_token: str) -> None:
    db = get_db()
    await db["refresh_tokens"].update_one(
        {"token_hash": _hash(raw_token)},
        {"$set": {"revoked": True}},
    )
