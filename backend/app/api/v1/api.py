from fastapi import APIRouter

from app.api.v1.endpoints import consultation, patients, tts
from app.auth import router as auth_router

api_router = APIRouter()
api_router.include_router(auth_router.router, prefix="/auth", tags=["auth"])
api_router.include_router(patients.router)
api_router.include_router(consultation.router, prefix="/consultation", tags=["consultation"])
api_router.include_router(tts.router, prefix="/note", tags=["tts"])
