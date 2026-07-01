from fastapi import APIRouter, Depends
from fastapi.responses import Response
from pydantic import BaseModel

from app.agent.tts.service import synthesize
from app.auth.deps import verify_token

router = APIRouter()


class SpeakRequest(BaseModel):
    text: str


@router.post("/speak", dependencies=[Depends(verify_token)])
async def speak(body: SpeakRequest) -> Response:
    audio_bytes = await synthesize(body.text)
    return Response(content=audio_bytes, media_type="audio/mpeg")
