from contextlib import asynccontextmanager

import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.api import api_router
from app.core.config import settings
from app.core.database import close_db, get_db

logging.basicConfig(
    level=logging.DEBUG if settings.DEBUG else logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("Starting kuvaka backend v%s", settings.VERSION)
    try:
        db = get_db()
        await db["sessions"].create_index([("session_id", 1)], unique=True)
        await db["sessions"].create_index([("created_at", -1)])
        log.info("MongoDB connected and indexes ensured")
    except Exception as exc:
        log.warning("MongoDB index setup failed (will retry on first request): %s", exc)
    yield
    await close_db()
    log.info("Shutdown complete")


app = FastAPI(
    title=settings.PROJECT_NAME,
    version=settings.VERSION,
    lifespan=lifespan,
)

# "allow_credentials=True" is incompatible with allow_origins=["*"] per the CORS spec;
# use explicit origin list whenever possible, fall back to wildcard without credentials.
if settings.BACKEND_CORS_ALLOW_ALL:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )
else:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.BACKEND_CORS_ORIGINS or ["http://localhost:3000"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

app.include_router(api_router, prefix=settings.API_V1_STR)


@app.get("/health")
async def health():
    return {"status": "ok", "version": settings.VERSION}
