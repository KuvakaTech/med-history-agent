from fastapi import APIRouter

from app.api.v2.endpoints.ticketing import router as ticketing_router
from app.api.v2.endpoints.ticketing_admin import router as admin_router
from app.api.v2.endpoints.setup import router as setup_router

api_v2_router = APIRouter()

# One-time bootstrap (secret-gated)
api_v2_router.include_router(setup_router, tags=["setup"])

# Public patient-facing routes: /api/v2/t/{slug}/...
api_v2_router.include_router(ticketing_router, prefix="/t", tags=["ticketing"])

# Admin routes: /api/v2/admin/...
api_v2_router.include_router(admin_router, prefix="/admin", tags=["ticketing-admin"])
