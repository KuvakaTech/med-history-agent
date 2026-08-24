"""One-time bootstrap script — creates a hospital and optionally elevates a user.

Usage:
    .venv/bin/python bootstrap_hospital.py

Run from the backend/ directory after the server is running.
"""
import asyncio
import os
import sys

os.environ.setdefault("JWT_SECRET_KEY", "")

# ── config ────────────────────────────────────────────────────
HOSPITAL_SLUG  = "aiims"
HOSPITAL_NAME  = "AIIMS Delhi"
HOSPITAL_LANG  = "hi"

# Set this to the email of the account you want to make super_admin
# Leave blank to skip user elevation
ELEVATE_EMAIL  = ""   # e.g. "you@example.com"
# ─────────────────────────────────────────────────────────────


async def main():
    from dotenv import load_dotenv
    load_dotenv(".env")

    from app.core.database import get_db
    from app.ticketing.models import Hospital
    from app.ticketing.hospital_store import hospital_store

    db = get_db()

    # 1. Create the hospital
    existing = await hospital_store.get_by_slug(HOSPITAL_SLUG)
    if existing:
        print(f"✓ Hospital '{HOSPITAL_SLUG}' already exists (id: {existing.hospital_id})")
        hospital = existing
    else:
        hospital = Hospital(
            slug=HOSPITAL_SLUG,
            name=HOSPITAL_NAME,
            default_language=HOSPITAL_LANG,
        )
        await hospital_store.create(hospital)
        print(f"✓ Created hospital '{HOSPITAL_NAME}' → slug='{HOSPITAL_SLUG}' id={hospital.hospital_id}")

    # 2. List seeded categories
    cats = await hospital_store.list_categories(hospital.hospital_id)
    print(f"  {len(cats)} departments seeded (general_medicine, gynecology, etc.)")

    # 3. Optionally elevate a user to super_admin
    if ELEVATE_EMAIL:
        result = await db["users"].update_one(
            {"email": ELEVATE_EMAIL.lower().strip()},
            {"$set": {"role": "super_admin"}}
        )
        if result.matched_count:
            print(f"✓ Elevated '{ELEVATE_EMAIL}' to super_admin")
        else:
            print(f"✗ User '{ELEVATE_EMAIL}' not found — register first at http://localhost:3000/register")

    print("\nDone! Visit http://localhost:3000/checkin/aiims/start to test the patient flow.")

    from app.core.database import close_db
    await close_db()


if __name__ == "__main__":
    asyncio.run(main())
