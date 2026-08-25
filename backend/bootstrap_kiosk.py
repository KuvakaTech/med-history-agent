"""One-time bootstrap — create Varanasi Jan Sunwai kiosk centre.

Usage (from backend/):
    .venv/bin/python bootstrap_kiosk.py
"""
import asyncio

from dotenv import load_dotenv

CENTRE_SLUG = "varanasi-jan-sunwai"
CENTRE_NAME = "Varanasi Jan Sunwai"
CENTRE_LANG = "hi"


async def main():
    load_dotenv(".env")

    from app.core.database import close_db
    from app.kiosk.centre_store import centre_store
    from app.kiosk.models import KioskCentre

    existing = await centre_store.get_by_slug(CENTRE_SLUG)
    if existing:
        print(
            f"✓ Centre '{CENTRE_SLUG}' already exists (id={existing.centre_id})"
        )
    else:
        centre = KioskCentre(
            slug=CENTRE_SLUG,
            name=CENTRE_NAME,
            default_language=CENTRE_LANG,
        )
        await centre_store.create(centre)
        print(
            f"✓ Created centre '{CENTRE_NAME}' → slug='{CENTRE_SLUG}' id={centre.centre_id}"
        )

    print(f"\nDemo URL: http://localhost:3000/kiosk/{CENTRE_SLUG}/start")
    await close_db()


if __name__ == "__main__":
    asyncio.run(main())
