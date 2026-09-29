"""One-time bootstrap — Charitas CHK hospital + hospital_admin user.

Usage (from backend/, with .env pointing at your MongoDB):

    python bootstrap_charitas_chk.py

Idempotent: skips hospital/user if they already exist.
"""
from __future__ import annotations

import asyncio
import os
import sys

os.environ.setdefault("JWT_SECRET_KEY", "")

HOSPITAL_SLUG = "charitas-chk"
HOSPITAL_NAME = "Charitas – Campus Helmholtz-Klinikum (CHK)"
HOSPITAL_LANG = "en"
KIOSK_PIN = "123456"  # 6 digits — change after first login via Admin → Kiosk PIN

ADMIN_EMAIL = "martin@gmail.com"
ADMIN_NAME = "Martin"
ADMIN_PASSWORD = "1234567890"


async def main() -> None:
    from dotenv import load_dotenv

    load_dotenv(".env")

    from app.auth import user_store
    from app.core.database import close_db, get_db
    from app.ticketing.hospital_store import hospital_store
    from app.ticketing.models import Hospital

    hospital = await hospital_store.get_by_slug(HOSPITAL_SLUG)
    if hospital:
        print(f"OK Hospital '{HOSPITAL_SLUG}' already exists (id={hospital.hospital_id})")
        if hospital.default_language != HOSPITAL_LANG:
            hospital = await hospital_store.set_default_language(
                hospital.hospital_id, HOSPITAL_LANG
            )
            print(f"  Updated default_language → {HOSPITAL_LANG}")
    else:
        hospital = Hospital(
            slug=HOSPITAL_SLUG,
            name=HOSPITAL_NAME,
            default_language=HOSPITAL_LANG,
        )
        await hospital_store.create(hospital)
        print(f"OK Created hospital '{HOSPITAL_NAME}' slug={HOSPITAL_SLUG} id={hospital.hospital_id}")

    if KIOSK_PIN:
        await hospital_store.set_kiosk_pin(hospital.hospital_id, KIOSK_PIN)
        print(f"  Kiosk PIN set ({len(KIOSK_PIN)} digits). Change in admin after go-live.")

    cats = await hospital_store.list_categories(hospital.hospital_id)
    print(f"  {len(cats)} departments available.")

    db = get_db()
    existing = await db["users"].find_one({"email": ADMIN_EMAIL.lower()})
    if existing:
        print(f"OK User '{ADMIN_EMAIL}' already exists (role={existing.get('role')})")
        if existing.get("hospital_id") != hospital.hospital_id:
            await db["users"].update_one(
                {"email": ADMIN_EMAIL.lower()},
                {"$set": {"hospital_id": hospital.hospital_id, "role": "hospital_admin"}},
            )
            print("  Linked user to this hospital as hospital_admin.")
    else:
        hashed = user_store.hash_password(ADMIN_PASSWORD)
        await user_store.create_admin(
            email=ADMIN_EMAIL,
            name=ADMIN_NAME,
            hashed_password=hashed,
            role="hospital_admin",
            hospital_id=hospital.hospital_id,
        )
        print(f"OK Created hospital_admin '{ADMIN_EMAIL}'")

    print("\n--- Next steps ---")
    print(f"  Admin login:  /login  ({ADMIN_EMAIL})")
    print(f"  Kiosk check-in: /checkin/{HOSPITAL_SLUG}/start")
    print(f"  Language: {HOSPITAL_LANG} (voice + SOAP summary)")
    print("  Rotate the admin password after first login if this script was run in a shared environment.")

    await close_db()


if __name__ == "__main__":
    asyncio.run(main())
