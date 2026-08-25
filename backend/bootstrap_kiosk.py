"""One-time bootstrap — create Varanasi kiosk centres.

Usage (from backend/):
    .venv/bin/python bootstrap_kiosk.py
"""
import asyncio

from dotenv import load_dotenv

CENTRES = [
    {
        "slug": "varanasi-jan-sunwai",
        "name": "Varanasi Jan Sunwai",
        "default_language": "hi",
        "prompt_file": "jan_sunwai_system.txt",
        "complaint_prefix": "JS-VNS",
    },
    {
        "slug": "varanasi-nagar-nigam",
        "name": "Varanasi Nagar Nigam",
        "default_language": "hi",
        "prompt_file": "nagar_nigam_system.txt",
        "complaint_prefix": "NN-VNS",
    },
]


async def main():
    load_dotenv(".env")

    from app.core.database import close_db
    from app.kiosk.centre_store import centre_store
    from app.kiosk.models import KioskCentre

    for cfg in CENTRES:
        existing = await centre_store.get_by_slug(cfg["slug"])
        if existing:
            print(f"✓ Centre '{cfg['slug']}' already exists (id={existing.centre_id})")
        else:
            centre = KioskCentre(**cfg)
            await centre_store.create(centre)
            print(
                f"✓ Created centre '{cfg['name']}' → slug='{cfg['slug']}' id={centre.centre_id}"
            )
        print(f"  Demo URL: http://localhost:3000/kiosk/{cfg['slug']}/start")

    await close_db()


if __name__ == "__main__":
    asyncio.run(main())
