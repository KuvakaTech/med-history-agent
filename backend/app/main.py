from contextlib import asynccontextmanager

import logging

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from app.api.v1.api import api_router
from app.api.v2.api import api_v2_router
from app.core.config import settings
from app.core.database import close_db, get_db
from app.core.ratelimit import limiter

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
        await db["sessions"].create_index([("user_id", 1), ("session_id", 1)])
        await db["sessions"].create_index([("patient_id", 1), ("user_id", 1)])
        # Users
        await db["users"].create_index("email", unique=True)
        # Refresh tokens — TTL index auto-deletes expired documents; hash index for lookups
        await db["refresh_tokens"].create_index("expires_at", expireAfterSeconds=0)
        await db["refresh_tokens"].create_index("token_hash", unique=True)
        # Patients
        await db["patients"].create_index("patient_id", unique=True)
        await db["patients"].create_index([("doctor_id", 1), ("created_at", -1)])
        # Cabin consultations
        await db["cabin_sessions"].create_index([("session_id", 1)], unique=True)
        await db["cabin_sessions"].create_index([("doctor_id", 1), ("created_at", -1)])
        await db["cabin_sessions"].create_index([("patient_id", 1), ("doctor_id", 1)])
        # Cabin leases. session_id is the document _id, so the uniqueness that decides
        # the acquire race is already enforced by the primary key. The TTL index is
        # hygiene for leases orphaned by a hard worker crash — Mongo's TTL monitor only
        # runs about once a minute, so acquire() compares expires_at itself rather than
        # relying on it.
        await db["cabin_leases"].create_index("expires_at", expireAfterSeconds=0)
        await db["cabin_leases"].create_index([("doctor_id", 1)])
        # Ticketing v2
        await db["ticket_hospitals"].create_index("hospital_id", unique=True)
        await db["ticket_hospitals"].create_index("slug", unique=True)
        await db["ticket_categories"].create_index("category_id", unique=True)
        await db["ticket_categories"].create_index([("hospital_id", 1), ("active", 1)])
        # phone is globally unique — one patient record regardless of hospital
        await db["ticket_patients"].create_index("patient_id", unique=True)
        await db["ticket_patients"].create_index("phone", unique=True)
        await db["ticket_sessions"].create_index("session_id", unique=True)
        await db["ticket_sessions"].create_index("ticket_number", unique=True, sparse=True)
        await db["ticket_sessions"].create_index([("hospital_id", 1), ("started_at", -1)])
        await db["ticket_sessions"].create_index([("patient_id", 1)])
        await db["ticket_sessions"].create_index([("hospital_id", 1), ("status", 1)])
        # ticket_number counter document — _id already has a built-in unique index
        # in every MongoDB collection, so no explicit index creation needed here
        # await db["ticket_counters"].create_index("_id", unique=True)
        # Kiosk (Jan Sunwai)
        await db["kiosk_centres"].create_index("centre_id", unique=True)
        await db["kiosk_centres"].create_index("slug", unique=True)
        await db["kiosk_sessions"].create_index("session_id", unique=True)
        # Partial unique index — Mongo sparse indexes still index explicit nulls.
        try:
            await db["kiosk_sessions"].drop_index("complaint_number_1")
        except Exception:
            pass
        await db["kiosk_sessions"].create_index(
            "complaint_number",
            unique=True,
            partialFilterExpression={"complaint_number": {"$type": "string"}},
        )
        await db["kiosk_sessions"].update_many(
            {"complaint_number": None},
            {"$unset": {"complaint_number": ""}},
        )
        await db["kiosk_sessions"].create_index([("centre_id", 1), ("started_at", -1)])
        await db["kiosk_sessions"].create_index([("centre_id", 1), ("status", 1)])
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

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(SlowAPIMiddleware)

# "allow_credentials=True" is incompatible with a literal allow_origins=["*"] per the
# CORS spec, and the frontend relies on credentialed requests (cookie fallback on
# login/refresh/logout). allow_origin_regex reflects the exact request origin instead,
# so "allow all" still works with credentials.
if settings.BACKEND_CORS_ALLOW_ALL:
    app.add_middleware(
        CORSMiddleware,
        allow_origin_regex=r".*",
        allow_credentials=True,
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


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    # A catch-all Exception handler runs inside Starlette's ServerErrorMiddleware, which
    # sits OUTSIDE CORSMiddleware — its response never passes through CORS processing, so
    # browsers report the 500 as a CORS failure. Attach the CORS headers manually here,
    # honouring the same origin policy as the middleware config.
    log.exception("Unhandled exception on %s %s", request.method, request.url.path)
    headers = {}
    origin = request.headers.get("origin")
    allowed = settings.BACKEND_CORS_ORIGINS or ["http://localhost:3000"]
    if origin and (settings.BACKEND_CORS_ALLOW_ALL or origin in allowed):
        headers["Access-Control-Allow-Origin"] = origin
        headers["Access-Control-Allow-Credentials"] = "true"
        headers["Vary"] = "Origin"
    return JSONResponse(
        status_code=500, content={"detail": "Internal server error."}, headers=headers
    )


app.include_router(api_router, prefix=settings.API_V1_STR)
app.include_router(api_v2_router, prefix="/api/v2")

# Dev-only harness for exercising the cabin WebSocket (getUserMedia needs a secure
# context, which file:// is not — this must be same-origin with the API). Never
# mount this in production: it's an unauthenticated static file server.
if settings.DEBUG or settings.CABIN_TEST_HARNESS:
    app.mount("/dev", StaticFiles(directory="app/static"), name="dev")


@app.get("/health")
async def health():
    return {"status": "ok", "version": settings.VERSION}
