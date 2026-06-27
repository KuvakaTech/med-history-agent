from fastapi import APIRouter

from app.api.v1.endpoints import consultation, tts

api_router = APIRouter()
api_router.include_router(consultation.router, prefix="/consultation", tags=["consultation"])
api_router.include_router(tts.router, prefix="/note", tags=["tts"])
