"""One-time setup endpoint — creates a hospital + super_admin account.

Protected by ?secret= matching JWT_SECRET_KEY so it's not open.
Safe to call multiple times — idempotent.

POST /api/v2/setup
Body: {
  "secret": "<JWT_SECRET_KEY from .env>",
  "hospital_slug": "aiims",
  "hospital_name": "AIIMS Delhi",
  "admin_email": "admin@kuvaka.ai",
  "admin_name": "Super Admin",
  "admin_password": "Admin1234"
}
"""
from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, EmailStr

from app.auth import user_store
from app.core.config import settings
from app.ticketing.hospital_store import hospital_store
from app.ticketing.models import Hospital

router = APIRouter()


class SetupRequest(BaseModel):
    secret: str
    hospital_slug: str = "aiims"
    hospital_name: str = "AIIMS Delhi"
    admin_email: EmailStr
    admin_name: str = "Super Admin"
    admin_password: str


@router.post("/setup")
async def one_time_setup(body: SetupRequest):
    # Gate with JWT secret — anyone who can read the .env can bootstrap
    if body.secret != settings.JWT_SECRET_KEY:
        raise HTTPException(status_code=403, detail="Invalid secret.")

    results = {}

    # 1. Create hospital
    slug = body.hospital_slug.strip().lower().replace(" ", "-")
    existing_hospital = await hospital_store.get_by_slug(slug)
    if existing_hospital:
        results["hospital"] = f"already exists (id={existing_hospital.hospital_id})"
        hospital_id = existing_hospital.hospital_id
    else:
        hospital = Hospital(
            slug=slug,
            name=body.hospital_name.strip(),
            default_language="hi",
        )
        await hospital_store.create(hospital)
        results["hospital"] = f"created '{slug}' with {15} departments (id={hospital.hospital_id})"
        hospital_id = hospital.hospital_id

    # 2. Create super_admin user
    try:
        hashed = user_store.hash_password(body.admin_password)
        new_user = await user_store.create_admin(
            email=body.admin_email,
            name=body.admin_name.strip(),
            hashed_password=hashed,
            role="super_admin",
            hospital_id=None,
        )
        results["admin"] = f"created super_admin '{body.admin_email}'"
    except ValueError:
        # Already exists — elevate to super_admin
        from app.core.database import get_db
        db = get_db()
        await db["users"].update_one(
            {"email": body.admin_email.lower()},
            {"$set": {"role": "super_admin", "hospital_id": None}},
        )
        results["admin"] = f"elevated '{body.admin_email}' to super_admin"

    results["hospital_id"] = hospital_id
    results["next_steps"] = [
        f"Login at http://localhost:3000/login with {body.admin_email}",
        f"Patient check-in: http://localhost:3000/checkin/{slug}/start",
        "Admin dashboard: http://localhost:3000/admin",
        f"Create hospital_admin: POST /api/v2/admin/users with role=hospital_admin + hospital_id={hospital_id}",
    ]

    return results
