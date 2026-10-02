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
        "centre_kind": "grievance",
        "prompt_file": "jan_sunwai_system.txt",
        "complaint_prefix": "JS-VNS",
    },
    {
        "slug": "varanasi-jan-sunwai-v3",
        "name": "Varanasi Jan Sunwai v3",
        "default_language": "hi",
        "centre_kind": "grievance",
        "prompt_file": "jan_sunwai_v3_system.txt",
        "complaint_prefix": "JS-VNS",
    },
    {
        "slug": "barwani-jan-sunwai",
        "name": "Barwani Jan Sunwai",
        "default_language": "hi",
        "centre_kind": "grievance",
        "prompt_file": "barwani_jan_sunwai",
        "complaint_prefix": "JS-BWN",
    },
    {
        "slug": "varanasi-nagar-nigam",
        "name": "Varanasi Nagar Nigam",
        "default_language": "hi",
        "centre_kind": "grievance",
        "prompt_file": "nagar_nigam_system.txt",
        "complaint_prefix": "NN-VNS",
    },
    {
        "slug": "barwani-guddi",
        "name": "Guddi Learning",
        "default_language": "hi",
        "centre_kind": "learning",
        "prompt_file": "guddi_learning_system.txt",
    },
    {
        "slug": "barwani-guddi-v4",
        "name": "Guddi Hindi Seekho",
        "default_language": "hi",
        "centre_kind": "talk",
        "prompt_file": "guddi_talk_system.txt",
    },
    {
        "slug": "barwani-guddi-v5",
        "name": "Guddi v5 Hindi Seekho",
        "default_language": "hi",
        "centre_kind": "talk",
        "prompt_file": "guddi_v5_talk_system.txt",
    },
    {
        "slug": "barwani-guddi-v6",
        "name": "Guddi v6 Hindi Seekho",
        "default_language": "hi",
        "centre_kind": "talk",
        "prompt_file": "guddi_v6_talk_system.txt",
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
            kind_changed = existing.centre_kind != cfg["centre_kind"]
            prompt_changed = existing.prompt_file != cfg.get("prompt_file")
            if cfg["slug"] == "barwani-guddi-v4" and (kind_changed or prompt_changed):
                existing.centre_kind = cfg["centre_kind"]
                existing.prompt_file = cfg.get("prompt_file")
                await centre_store.update(existing)
                print(
                    f"✓ Updated centre '{cfg['slug']}' → kind={existing.centre_kind} "
                    f"prompt={existing.prompt_file}"
                )
            else:
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
