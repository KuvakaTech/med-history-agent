"""Gemini Live wrapper for Jan Sunwai kiosk — single finish_complaint tool."""
from __future__ import annotations

import logging
import re
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

# Children pause more between words — longer end-of-speech for learning kiosk.
_LEARNING_SILENCE_MS = 750
_DEFAULT_SILENCE_MS = 400

_TOOL_LEAK_RE = re.compile(
    r"call:finish_(?:complaint|lesson)\{.*?(?:\}|$)",
    re.IGNORECASE | re.DOTALL,
)
_JANSUNWAI_RECORD_RE = re.compile(
    r"<<<JANSUNWAI_RECORD.*?JANSUNWAI_RECORD>>>",
    re.DOTALL | re.IGNORECASE,
)


def merge_transcript_chunk(buf: str, chunk: str) -> str:
    """Merge Gemini transcription chunks (incremental or cumulative)."""
    chunk = chunk or ""
    if not chunk:
        return buf
    if not buf:
        return chunk
    if chunk == buf:
        return buf
    if chunk.startswith(buf):
        return chunk
    if buf.endswith(chunk):
        return buf
    overlap = min(len(buf), len(chunk))
    for n in range(overlap, 0, -1):
        if buf.endswith(chunk[:n]):
            return buf + chunk[n:]
    return buf + chunk


def dedupe_concatenated_repeats(text: str) -> str:
    """Collapse exact whole-string repetition (e.g. closing line said 7×)."""
    t = (text or "").strip()
    n = len(t)
    if n < 2:
        return t
    for size in range(1, n // 2 + 1):
        if n % size != 0:
            continue
        unit = t[:size]
        if unit * (n // size) == t:
            return unit
    return t


def collapse_repeated_suffix(text: str, min_unit: int = 24) -> str:
    """If the same trailing phrase repeats, keep one copy."""
    t = (text or "").strip()
    changed = True
    while changed:
        changed = False
        if len(t) < min_unit * 2:
            break
        for size in range(len(t) // 2, min_unit - 1, -1):
            unit = t[-size:]
            count = 0
            pos = len(t)
            while pos >= size and t[pos - size : pos] == unit:
                count += 1
                pos -= size
            if count >= 2:
                t = t[:pos] + unit
                changed = True
                break
    return t


def collapse_consecutive_repeats(text: str, min_unit: int = 24) -> str:
    """Collapse consecutive identical substrings (mid-text or trailing)."""
    t = (text or "").strip()
    changed = True
    while changed:
        changed = False
        if len(t) < min_unit * 2:
            break
        for size in range(len(t) // 2, min_unit - 1, -1):
            i = 0
            while i + size * 2 <= len(t):
                unit = t[i : i + size]
                end = i + size
                while end + size <= len(t) and t[end : end + size] == unit:
                    end += size
                if end - i >= size * 2:
                    t = t[: i + size] + t[end:]
                    changed = True
                    break
                i += 1
            if changed:
                break
    return t


def sanitize_agent_transcript(text: str) -> str:
    """Strip leaked tool-call syntax, record blocks, and repeated closing phrases."""
    cleaned = _JANSUNWAI_RECORD_RE.sub("", text or "")
    cleaned = _TOOL_LEAK_RE.sub("", cleaned).strip()
    cleaned = dedupe_concatenated_repeats(cleaned)
    cleaned = collapse_consecutive_repeats(cleaned)
    return collapse_repeated_suffix(cleaned)


def bcp47_language(code: str) -> str:
    return LANGUAGE_TO_BCP47.get((code or "").lower().strip(), "hi-IN")


def hindi_transcription_config() -> AudioTranscriptionConfig:
    """Match ticketing gemini_live — default ASR; captions normalized in hindi_display."""
    return AudioTranscriptionConfig()


def kiosk_voice_name(learning: bool = False) -> str:
    if learning:
        return settings.GUDDI_GEMINI_LIVE_VOICE or settings.KIOSK_GEMINI_LIVE_VOICE or "Kore"
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


def lesson_tools() -> list[Tool]:
    return [
        Tool(
            function_declarations=[
                FunctionDeclaration(
                    name="show_word_card",
                    description=(
                        "Show a vocabulary picture on the kiosk screen for the child. "
                        "Call BEFORE naming or quizzing a word. mode=teach when introducing; "
                        "mode=quiz when asking the child to name the picture (system checks answer)."
                    ),
                    parameters=Schema(
                        type=Type.OBJECT,
                        properties={
                            "word_id": Schema(
                                type=Type.STRING,
                                description=(
                                    "Vocabulary id, e.g. aam, roti, bakri, laal, ek, aankh"
                                ),
                            ),
                            "mode": Schema(
                                type=Type.STRING,
                                description="teach or quiz",
                                enum=["teach", "quiz"],
                            ),
                        },
                        required=["word_id", "mode"],
                    ),
                ),
                FunctionDeclaration(
                    name="finish_lesson",
                    description=(
                        "Call when the Hindi lesson is complete: words taught, "
                        "child celebrated, and warm close done. Also call if the "
                        "child wants to stop early."
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


def complaint_tools(*, v3: bool = False) -> list[Tool]:
    properties: dict = {
        "reason": Schema(
            type=Type.STRING,
            description="Why the session is ending",
        ),
    }
    required = ["reason"]
    description = (
        "Call ONCE immediately after section 11 — deliver a single goodbye, "
        "then call this tool. Do not repeat closing phrases or keep talking. "
        "Also call if the citizen wants to stop after partial capture."
    )
    if v3:
        description = (
            "Call ONCE immediately after the spoken close (Section 15A or 15B) — "
            "deliver a single goodbye, then call this tool with session_type and "
            "print_mode. Do not repeat closing phrases or keep talking."
        )
        properties["session_type"] = Schema(
            type=Type.STRING,
            description=(
                "complaint | information | help_desk | mixed — primary session mode"
            ),
        )
        properties["print_mode"] = Schema(
            type=Type.STRING,
            description="application_letter | info_sheet | none",
        )
        required = ["reason", "session_type", "print_mode"]
    return [
        Tool(
            function_declarations=[
                FunctionDeclaration(
                    name="finish_complaint",
                    description=description,
                    parameters=Schema(
                        type=Type.OBJECT,
                        properties=properties,
                        required=required,
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
    learning: bool = False,
) -> LiveConnectConfig:
    model_id = model or settings.GEMINI_LIVE_MODEL
    transcription = hindi_transcription_config()
    silence_ms = _LEARNING_SILENCE_MS if learning else _DEFAULT_SILENCE_MS
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
                silence_duration_ms=silence_ms,
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
        self._user_final_emitted = False

    async def connect(
        self,
        system_instruction: str,
        *,
        language: str = "hi",
        tools: Optional[list[Tool]] = None,
        session_handle: Optional[str] = None,
        learning: bool = False,
    ) -> None:
        api_key = settings.GOOGLE_API_KEY
        if not api_key:
            raise RuntimeError("GOOGLE_API_KEY is not set")
        self._closed = False
        self._user_buf = ""
        self._agent_buf = ""
        self._user_speaking = False
        self._user_final_emitted = False
        handle = session_handle if session_handle is not None else self._session_handle
        config = build_live_config(
            system_instruction,
            language_code=bcp47_language(language),
            voice=kiosk_voice_name(learning=learning),
            tools=tools,
            session_handle=handle,
            model=settings.GEMINI_LIVE_MODEL,
            learning=learning,
        )
        self._client = genai.Client(api_key=api_key)
        self._cm = self._client.aio.live.connect(
            model=settings.GEMINI_LIVE_MODEL,
            config=config,
        )
        self._session = await self._cm.__aenter__()
        log.info(
            "Kiosk Gemini Live connected model=%s lang=%s learning=%s",
            settings.GEMINI_LIVE_MODEL,
            bcp47_language(language),
            learning,
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

    def force_finalize_user(self) -> str:
        """Finalize buffered user speech; return text or empty string."""
        if self._user_final_emitted:
            return ""
        text = self._user_buf.strip()
        self._user_buf = ""
        self._user_speaking = False
        if text:
            self._user_final_emitted = True
        return text

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
                self._user_final_emitted = False
                events.append(LiveEvent(kind="user_speech_started"))
            self._user_buf = merge_transcript_chunk(self._user_buf, interim.text)
            events.append(
                LiveEvent(kind="user_transcript_partial", text=self._user_buf)
            )

        inp = getattr(content, "input_transcription", None)
        if inp is not None and inp.text:
            if not self._user_speaking:
                self._user_speaking = True
                self._user_final_emitted = False
                events.append(LiveEvent(kind="user_speech_started"))
            self._user_buf = merge_transcript_chunk(self._user_buf, inp.text)
            events.append(
                LiveEvent(kind="user_transcript_partial", text=self._user_buf)
            )
            if inp.finished:
                text = self._user_buf.strip()
                self._user_buf = ""
                self._user_speaking = False
                if text and not self._user_final_emitted:
                    self._user_final_emitted = True
                    events.append(LiveEvent(kind="user_transcript_final", text=text))

        out = getattr(content, "output_transcription", None)
        if out is not None and out.text:
            self._agent_buf = merge_transcript_chunk(self._agent_buf, out.text)
            partial = sanitize_agent_transcript(self._agent_buf)
            if partial:
                events.append(
                    LiveEvent(kind="agent_transcript_partial", text=partial)
                )
            if out.finished:
                text = sanitize_agent_transcript(self._agent_buf.strip())
                self._agent_buf = ""
                if text:
                    events.append(LiveEvent(kind="agent_transcript_final", text=text))

        model_turn = getattr(content, "model_turn", None)
        if model_turn is not None:
            if self._user_buf.strip() and not self._user_final_emitted:
                self._user_final_emitted = True
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
                text = sanitize_agent_transcript(self._agent_buf.strip())
                if text:
                    events.append(
                        LiveEvent(kind="agent_transcript_final", text=text)
                    )
                self._agent_buf = ""
            if self._user_buf.strip() and not self._user_final_emitted:
                self._user_final_emitted = True
                events.append(
                    LiveEvent(
                        kind="user_transcript_final",
                        text=self._user_buf.strip(),
                    )
                )
                self._user_buf = ""
                self._user_speaking = False
            self._user_final_emitted = False
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
