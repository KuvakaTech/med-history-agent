from fastapi import APIRouter
from fastapi.responses import Response
from pydantic import BaseModel

from app.agent.tts.service import synthesize

router = APIRouter()


class SpeakRequest(BaseModel):
    text: str


@router.post("/speak")
async def speak(body: SpeakRequest) -> Response:
    audio_bytes = await synthesize(body.text)
    return Response(content=audio_bytes, media_type="audio/mpeg")
