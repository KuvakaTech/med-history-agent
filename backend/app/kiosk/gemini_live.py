"""Gemini Live wrapper for Jan Sunwai kiosk — single finish_complaint tool."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Optional

from google import genai
from google.genai.types import (
    AudioTranscriptionConfig,
    AutomaticActivityDetection,
    Blob,
    ContextWindowCompressionConfig,
    EndSensitivity,
    FunctionDeclaration,
    FunctionResponse,
    LiveConnectConfig,
    RealtimeInputConfig,
    Schema,
    SessionResumptionConfig,
    SlidingWindow,
    SpeechConfig,
    StartSensitivity,
    ThinkingConfig,
    Tool,
    Type,
    VoiceConfig,
    PrebuiltVoiceConfig,
)

from app.core.config import settings

log = logging.getLogger(__name__)

INPUT_MIME = "audio/pcm;rate=16000"
OUTPUT_RATE_HZ = 24000

LANGUAGE_TO_BCP47: dict[str, str] = {
    "hi": "hi-IN",
    "en": "en-IN",
    "mr": "mr-IN",
    "gu": "gu-IN",
    "ta": "ta-IN",
    "te": "te-IN",
}


def bcp47_language(code: str) -> str:
    return LANGUAGE_TO_BCP47.get((code or "").lower().strip(), "hi-IN")


def hindi_transcription_config() -> AudioTranscriptionConfig:
    """Match ticketing gemini_live — default ASR; captions normalized in hindi_display."""
    return AudioTranscriptionConfig()


def kiosk_voice_name() -> str:
    return settings.KIOSK_GEMINI_LIVE_VOICE or "Kore"


def is_native_audio_model(model: str) -> bool:
    name = (model or "").lower()
    return "native-audio" in name or "gemini-3" in name


@dataclass
class LiveEvent:
    kind: str
    audio: bytes = b""
    text: str = ""
    tool_name: str = ""
    tool_args: dict[str, Any] = field(default_factory=dict)
    tool_call_id: Optional[str] = None
    error: str = ""
    handle: str = ""


def complaint_tools() -> list[Tool]:
    return [
        Tool(
            function_declarations=[
                FunctionDeclaration(
                    name="finish_complaint",
                    description=(
                        "Call when the grievance is complete: problem fully captured, "
                        "identity and address confirmed, complaint location captured, "
                        "and the citizen has confirmed the summary. Also call if they "
                        "want to stop after a partial capture."
                    ),
                    parameters=Schema(
                        type=Type.OBJECT,
                        properties={
                            "reason": Schema(
                                type=Type.STRING,
                                description="Why the session is ending",
                            ),
                        },
                        required=["reason"],
                    ),
                )
            ]
        )
    ]


def build_live_config(
    system_instruction: str,
    *,
    language_code: str,
    voice: str,
    tools: Optional[list[Tool]] = None,
    session_handle: Optional[str] = None,
    model: Optional[str] = None,
) -> LiveConnectConfig:
    model_id = model or settings.GEMINI_LIVE_MODEL
    transcription = hindi_transcription_config()
    config = LiveConnectConfig(
        response_modalities=["AUDIO"],
        system_instruction=system_instruction,
        speech_config=SpeechConfig(
            voice_config=VoiceConfig(
                prebuilt_voice_config=PrebuiltVoiceConfig(voice_name=voice)
            ),
            language_code=language_code,
        ),
        tools=tools or None,
        input_audio_transcription=transcription,
        output_audio_transcription=transcription,
        realtime_input_config=RealtimeInputConfig(
            automatic_activity_detection=AutomaticActivityDetection(
                start_of_speech_sensitivity=StartSensitivity.START_SENSITIVITY_HIGH,
                end_of_speech_sensitivity=EndSensitivity.END_SENSITIVITY_HIGH,
                prefix_padding_ms=20,
                silence_duration_ms=400,
            )
        ),
        session_resumption=SessionResumptionConfig(handle=session_handle),
        context_window_compression=ContextWindowCompressionConfig(
            sliding_window=SlidingWindow()
        ),
    )
    if is_native_audio_model(model_id):
        config.thinking_config = ThinkingConfig(thinking_budget=0)
    return config


class GeminiLiveSession:
    def __init__(self) -> None:
        self._client: Optional[genai.Client] = None
        self._cm: Any = None
        self._session: Any = None
        self._closed = False
        self._session_handle: Optional[str] = None
        self._user_buf = ""
        self._agent_buf = ""
        self._user_speaking = False

    async def connect(
        self,
        system_instruction: str,
        *,
        language: str = "hi",
        tools: Optional[list[Tool]] = None,
        session_handle: Optional[str] = None,
    ) -> None:
        api_key = settings.GOOGLE_API_KEY
        if not api_key:
            raise RuntimeError("GOOGLE_API_KEY is not set")
        self._closed = False
        self._user_buf = ""
        self._agent_buf = ""
        self._user_speaking = False
        handle = session_handle if session_handle is not None else self._session_handle
        config = build_live_config(
            system_instruction,
            language_code=bcp47_language(language),
            voice=kiosk_voice_name(),
            tools=tools,
            session_handle=handle,
            model=settings.GEMINI_LIVE_MODEL,
        )
        self._client = genai.Client(api_key=api_key)
        self._cm = self._client.aio.live.connect(
            model=settings.GEMINI_LIVE_MODEL,
            config=config,
        )
        self._session = await self._cm.__aenter__()
        log.info(
            "Kiosk Gemini Live connected model=%s lang=%s",
            settings.GEMINI_LIVE_MODEL,
            bcp47_language(language),
        )

    async def send_audio(self, pcm16: bytes) -> None:
        if self._closed or not self._session or not pcm16:
            return
        await self._session.send_realtime_input(
            audio=Blob(data=pcm16, mime_type=INPUT_MIME)
        )

    async def send_text(self, text: str) -> None:
        if self._closed or not self._session or not text:
            return
        await self._session.send_realtime_input(text=text)

    async def send_tool_response(
        self,
        name: str,
        call_id: Optional[str],
        response: dict[str, Any],
    ) -> None:
        if self._closed or not self._session:
            return
        await self._session.send_tool_response(
            function_responses=FunctionResponse(
                name=name,
                id=call_id,
                response=response,
            )
        )

    async def receive(self) -> AsyncIterator[LiveEvent]:
        while not self._closed and self._session is not None:
            try:
                async for msg in self._session.receive():
                    if self._closed:
                        return
                    for event in self._parse(msg):
                        yield event
            except Exception as exc:
                if self._closed:
                    return
                log.error("Kiosk Gemini Live receive failed: %s", exc, exc_info=True)
                yield LiveEvent(kind="error", error="आवाज़ सत्र बाधित हो गया।")
                return

    def _parse(self, msg: Any) -> list[LiveEvent]:
        events: list[LiveEvent] = []

        update = getattr(msg, "session_resumption_update", None)
        if (
            update is not None
            and getattr(update, "resumable", False)
            and getattr(update, "new_handle", None)
        ):
            self._session_handle = update.new_handle
            events.append(LiveEvent(kind="session_resumed", handle=update.new_handle))

        if getattr(msg, "go_away", None) is not None:
            events.append(LiveEvent(kind="go_away"))

        tool_call = getattr(msg, "tool_call", None)
        if tool_call is not None:
            for fc in tool_call.function_calls or []:
                events.append(
                    LiveEvent(
                        kind="tool_call",
                        tool_name=fc.name or "",
                        tool_args=dict(fc.args or {}),
                        tool_call_id=fc.id,
                    )
                )

        content = getattr(msg, "server_content", None)
        if content is None:
            return events

        if getattr(content, "interrupted", False):
            self._agent_buf = ""
            events.append(LiveEvent(kind="interrupted"))

        interim = getattr(content, "interim_input_transcription", None)
        if interim is not None and interim.text:
            if not self._user_speaking:
                self._user_speaking = True
                events.append(LiveEvent(kind="user_speech_started"))
            events.append(LiveEvent(kind="user_transcript_partial", text=interim.text))

        inp = getattr(content, "input_transcription", None)
        if inp is not None and inp.text:
            if not self._user_speaking:
                self._user_speaking = True
                events.append(LiveEvent(kind="user_speech_started"))
            self._user_buf += inp.text
            events.append(
                LiveEvent(kind="user_transcript_partial", text=self._user_buf)
            )
            if inp.finished:
                text = self._user_buf.strip()
                self._user_buf = ""
                self._user_speaking = False
                if text:
                    events.append(LiveEvent(kind="user_transcript_final", text=text))

        out = getattr(content, "output_transcription", None)
        if out is not None and out.text:
            self._agent_buf += out.text
            events.append(
                LiveEvent(kind="agent_transcript_partial", text=self._agent_buf)
            )
            if out.finished:
                text = self._agent_buf.strip()
                self._agent_buf = ""
                if text:
                    events.append(LiveEvent(kind="agent_transcript_final", text=text))

        model_turn = getattr(content, "model_turn", None)
        if model_turn is not None:
            if self._user_buf.strip():
                events.append(
                    LiveEvent(kind="user_transcript_final", text=self._user_buf.strip())
                )
                self._user_buf = ""
                self._user_speaking = False
            for part in model_turn.parts or []:
                inline = getattr(part, "inline_data", None)
                if inline is not None and getattr(inline, "data", None):
                    events.append(
                        LiveEvent(kind="agent_audio_chunk", audio=inline.data)
                    )

        if getattr(content, "turn_complete", False):
            if self._agent_buf.strip():
                events.append(
                    LiveEvent(
                        kind="agent_transcript_final", text=self._agent_buf.strip()
                    )
                )
                self._agent_buf = ""
            events.append(LiveEvent(kind="turn_complete"))

        return events

    async def close(self) -> None:
        self._closed = True
        cm = self._cm
        self._cm = None
        self._session = None
        if cm is not None:
            try:
                await cm.__aexit__(None, None, None)
            except Exception:
                log.debug("Kiosk Gemini Live close ignored an error", exc_info=True)
