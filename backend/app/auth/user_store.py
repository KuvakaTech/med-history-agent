"""User store — MongoDB CRUD and password hashing."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

import bcrypt
from bson import ObjectId

from app.core.database import get_db


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(plain: str, hashed: str) -> bool:
    return bcrypt.checkpw(plain.encode(), hashed.encode())


async def create(email: str, name: str, hashed_password: str) -> dict:
    db = get_db()
    if await db["users"].find_one({"email": email.lower()}):
        raise ValueError("Email already registered.")
    doc = {
        "email": email.lower().strip(),
        "name": name.strip(),
        "hashed_password": hashed_password,
        "role": "doctor",
        "created_at": datetime.now(timezone.utc),
    }
    result = await db["users"].insert_one(doc)
    doc["_id"] = result.inserted_id
    return doc


async def create_admin(
    email: str,
    name: str,
    hashed_password: str,
    role: str,                        # hospital_admin | centre_admin | super_admin
    hospital_id: Optional[str] = None,
    centre_id: Optional[str] = None,
) -> dict:
    """Create an admin account. Called only by super_admin."""
    db = get_db()
    if await db["users"].find_one({"email": email.lower()}):
        raise ValueError("Email already registered.")
    doc = {
        "email": email.lower().strip(),
        "name": name.strip(),
        "hashed_password": hashed_password,
        "role": role,
        "hospital_id": hospital_id,
        "centre_id": centre_id,
        "created_at": datetime.now(timezone.utc),
    }
    result = await db["users"].insert_one(doc)
    doc["_id"] = result.inserted_id
    return doc


async def get_by_email(email: str) -> Optional[dict]:
    db = get_db()
    return await db["users"].find_one({"email": email.lower().strip()})


async def get_by_id(user_id: str) -> Optional[dict]:
    db = get_db()
    try:
        return await db["users"].find_one({"_id": ObjectId(user_id)})
    except Exception:
        return None


async def list_admins(
    hospital_id: Optional[str] = None,
    centre_id: Optional[str] = None,
) -> list[dict]:
    """List admin accounts. Scoped by hospital_id or centre_id if provided."""
    db = get_db()
    query: dict = {
        "role": {"$in": ["hospital_admin", "centre_admin", "super_admin"]},
    }
    if hospital_id:
        query["hospital_id"] = hospital_id
    if centre_id:
        query["centre_id"] = centre_id
    cursor = db["users"].find(query, {"hashed_password": 0, "_id": 0})
    return [doc async for doc in cursor]
