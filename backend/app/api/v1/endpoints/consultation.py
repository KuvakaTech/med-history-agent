"""Consultation endpoints — fully async, MongoDB-backed, R2 audio storage."""
from __future__ import annotations

import asyncio
import json
import uuid
from typing import Any, AsyncGenerator, Optional

import logging

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, ValidationError

from app.auth.deps import verify_token, verify_ws_token

from app.agent.summarization.service import SummarizationService
from app.agent.transcription.service import transcribe_bytes
from app.clinical.context import (
    ClinicalFlag,
    ConsultationContext,
    ConsultationStage,
    DiagnosisResult,
    DoctorOverride,
    PrescriptionResult,
    QAEntry,
    Specialty,
)
from app.clinical.questionnaire.answer_validation import is_valid_answer
from app.clinical.questionnaire.engine import LLMHistoryEngine
from app.clinical.services.completeness import CompletenessService
from app.clinical.services.diagnosis import DiagnosisService
from app.clinical.services.prescription import PrescriptionService
from app.clinical.services.translation import TranslationService
from app.clinical.session_store import session_store
from app.storage import r2

router = APIRouter()
log = logging.getLogger(__name__)

# Generic message shown to patients when an LLM/provider call fails — never leak raw
# provider errors (rate limits, auth, etc.) into the UI.
GENERIC_LLM_ERROR = "Something went wrong generating the next question. Please try again."
RETRY_UNCLEAR_MESSAGE = "We couldn't understand that. Please try again."

# ─────────────────────────────────────────────
# Request / Response models
# ─────────────────────────────────────────────


class StartRequest(BaseModel):
    specialty: Specialty
    patient_language: Optional[str] = None
    patient_name: Optional[str] = None
    patient_age: Optional[int] = None
    patient_gender: Optional[str] = None
    chief_complaint: Optional[str] = None
    patient_id: Optional[str] = None
    latitude: Optional[float] = Field(default=None, ge=-90, le=90)
    longitude: Optional[float] = Field(default=None, ge=-180, le=180)


class StartResponse(BaseModel):
    session_id: str
    specialty: str
    stage: str
    opening_question: str
    latitude: Optional[float] = None
    longitude: Optional[float] = None


class AnswerRequest(BaseModel):
    answer: str


class AnswerResponse(BaseModel):
    new_flags: list[ClinicalFlag] = []
    next_question: Optional[str] = None
    history_complete: bool = False
    retry_same_question: bool = False
    retry_message: Optional[str] = None


class SessionStateResponse(BaseModel):
    session_id: str
    specialty: str
    current_stage: str
    qa_count: int
    flags: list[ClinicalFlag]
    history_complete: bool
    has_summary: bool
    has_diagnosis: bool
    has_prescription: bool
    latitude: Optional[float] = None
    longitude: Optional[float] = None


class QALogResponse(BaseModel):
    qa_log: list[dict]
    flags: list[dict]
    raw_transcript: str
    translated_transcript: str


class EditAnswerRequest(BaseModel):
    answer: str


class PrescribeRequest(BaseModel):
    confirmed_diagnosis: str


class OverrideRequest(BaseModel):
    field: str
    value: Any
    reason: Optional[str] = None


# ─────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────


async def _get_session(session_id: str, user_id: str) -> ConsultationContext:
    ctx = await session_store.get(session_id, user_id=user_id)
    if not ctx:
        raise HTTPException(status_code=404, detail="Session not found.")
    return ctx


def _retry_response(ctx: ConsultationContext, message: str = RETRY_UNCLEAR_MESSAGE) -> AnswerResponse:
    return AnswerResponse(
        retry_same_question=True,
        retry_message=message,
        next_question=ctx.current_question,
        history_complete=False,
    )


def _record_answer(ctx: ConsultationContext, answer_text: str) -> None:
    """Append the patient's answer to the session log before calling LLM."""
    ctx.qa_log.append(
        QAEntry(
            question_id=f"turn_{len(ctx.qa_log) + 1}",
            question_text=ctx.current_question or "",
            answer=answer_text,
        )
    )
    ctx.raw_transcript += f"\nQ: {ctx.current_question}\nA: {answer_text}"


def _resolve_completion(
    ctx: ConsultationContext,
    is_complete: bool,
    question_text: str,
) -> tuple[bool, Optional[str]]:
    """
    Returns (effective_is_complete, effective_next_question).

    When meta says is_complete=True, always redirect — even if a closing
    statement was streamed. The text was already displayed to the user.
    """
    if is_complete:
        ctx.history_complete = True
        ctx.current_question = None
        return True, None

    ctx.current_question = question_text or None
    return False, question_text or None


async def _process_answer(
    ctx: ConsultationContext, answer_text: str
) -> AnswerResponse:
    if not is_valid_answer(answer_text):
        return _retry_response(ctx)

    _record_answer(ctx, answer_text)

    engine = LLMHistoryEngine(ctx.specialty, language=ctx.patient_language)
    ctx, turn = await engine.next_turn(ctx, answer_text)

    new_flags: list[ClinicalFlag] = getattr(turn, "_resolved_flags", [])
    is_complete, next_q = _resolve_completion(ctx, turn.is_complete, turn.question_text or "")
    await session_store.update(ctx)

    return AnswerResponse(new_flags=new_flags, next_question=next_q, history_complete=is_complete)


async def _stream_answer_generator(
    ctx: ConsultationContext, answer_text: str
) -> AsyncGenerator[str, None]:
    """
    SSE generator: streams question tokens then sends a done event.
    Two concurrent calls: token stream + meta (flags/completion).
    """
    if not is_valid_answer(answer_text):
        yield _sse("retry", {"message": RETRY_UNCLEAR_MESSAGE})
        return

    _record_answer(ctx, answer_text)

    engine = LLMHistoryEngine(ctx.specialty, language=ctx.patient_language)
    question_text = ""
    new_flags: list[ClinicalFlag] = []
    is_complete = False

    try:
        async for chunk in engine.next_turn_stream(ctx, answer_text):
            if isinstance(chunk, str):
                question_text += chunk
                yield _sse("token", {"text": chunk})
            elif isinstance(chunk, dict) and chunk.get("__done__"):
                is_complete = chunk["is_complete"]
                new_flags = chunk["new_flags"]
                question_text = chunk.get("question_text") or question_text.strip()
    except Exception as exc:
        log.error("answer-stream failed for session %s: %s", ctx.session_id, exc, exc_info=True)
        yield _sse("error", {"message": GENERIC_LLM_ERROR})
        return

    is_complete, next_q = _resolve_completion(ctx, is_complete, question_text)
    await session_store.update(ctx)

    yield _sse("done", {
        "next_question": next_q,
        "history_complete": is_complete,
        "new_flags": [f.model_dump(mode="json") for f in new_flags],
    })


# ─────────────────────────────────────────────
# Endpoints
# ─────────────────────────────────────────────


@router.post("/start", response_model=StartResponse)
async def start_consultation(body: StartRequest, user: dict = Depends(verify_token)) -> StartResponse:
    patient_name = body.patient_name
    patient_age = body.patient_age
    patient_gender = body.patient_gender

    if body.patient_id:
        from app.clinical import patient_store
        patient = await patient_store.get(patient_id=body.patient_id, doctor_id=user["sub"])
        if not patient:
            raise HTTPException(status_code=404, detail="Patient not found.")
        patient_name = patient.name
        patient_age = patient.age
        patient_gender = patient.gender

    ctx = ConsultationContext(
        session_id=str(uuid.uuid4()),
        specialty=body.specialty,
        patient_language=body.patient_language,
        patient_name=patient_name,
        patient_age=patient_age,
        patient_gender=patient_gender,
        chief_complaint=body.chief_complaint,
        patient_id=body.patient_id,
        latitude=body.latitude,
        longitude=body.longitude,
    )
    engine = LLMHistoryEngine(body.specialty, language=body.patient_language)
    opening = await engine.opening_question(
        patient_name=patient_name,
        patient_age=patient_age,
        patient_gender=patient_gender,
        chief_complaint=body.chief_complaint,
    )
    ctx.current_question = opening
    await session_store.create(ctx, user_id=user["sub"])

    return StartResponse(
        session_id=ctx.session_id,
        specialty=ctx.specialty.value,
        stage=ctx.current_stage.value,
        opening_question=opening,
        latitude=ctx.latitude,
        longitude=ctx.longitude,
    )


@router.get("/{session_id}", response_model=SessionStateResponse)
async def get_session(session_id: str, user: dict = Depends(verify_token)) -> SessionStateResponse:
    ctx = await _get_session(session_id, user["sub"])
    return SessionStateResponse(
        session_id=ctx.session_id,
        specialty=ctx.specialty.value,
        current_stage=ctx.current_stage.value,
        qa_count=len(ctx.qa_log),
        flags=ctx.flags,
        history_complete=ctx.history_complete,
        has_summary=ctx.summary is not None,
        has_diagnosis=ctx.diagnosis is not None,
        has_prescription=ctx.prescription is not None,
        latitude=ctx.latitude,
        longitude=ctx.longitude,
    )


@router.post("/{session_id}/answer", response_model=AnswerResponse)
async def submit_answer(session_id: str, body: AnswerRequest, user: dict = Depends(verify_token)) -> AnswerResponse:
    ctx = await _get_session(session_id, user["sub"])
    if ctx.current_stage != ConsultationStage.QUESTIONNAIRE:
        raise HTTPException(400, f"Session is in stage '{ctx.current_stage}', not questionnaire.")
    if not ctx.current_question:
        raise HTTPException(400, "No active question. Start a new session.")
    return await _process_answer(ctx, body.answer)


@router.post("/{session_id}/answer-stream")
async def submit_answer_stream(session_id: str, body: AnswerRequest, user: dict = Depends(verify_token)):
    """
    SSE endpoint — streams question tokens then sends a done event.
    Events: {type:"token",text:"word"} ... {type:"done",next_question,history_complete,new_flags}
    """
    ctx = await _get_session(session_id, user["sub"])
    if ctx.current_stage != ConsultationStage.QUESTIONNAIRE:
        raise HTTPException(400, f"Session is in stage '{ctx.current_stage}', not questionnaire.")
    if not ctx.current_question:
        raise HTTPException(400, "No active question.")
    return StreamingResponse(
        _stream_answer_generator(ctx, body.answer),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/{session_id}/answer-audio", response_model=AnswerResponse)
async def submit_answer_audio(
    session_id: str, audio_file: UploadFile = File(...), user: dict = Depends(verify_token)
) -> AnswerResponse:
    ctx = await _get_session(session_id, user["sub"])
    if ctx.current_stage != ConsultationStage.QUESTIONNAIRE:
        raise HTTPException(400, f"Session is in stage '{ctx.current_stage}', not questionnaire.")
    if not ctx.current_question:
        raise HTTPException(400, "No active question.")

    audio_data = await audio_file.read()
    mimetype = audio_file.content_type or "audio/webm"

    # Store audio in R2
    audio_key = await r2.upload_audio(audio_data, session_id, mime_type=mimetype)
    ctx.audio_keys.append(audio_key)

    # Transcribe
    answer_text = await transcribe_bytes(audio_data, mimetype, language=ctx.patient_language)

    # Translate if needed
    if ctx.patient_language and ctx.patient_language != ctx.clinical_language:
        translator = TranslationService()
        answer_text = await translator.translate(
            answer_text,
            source_lang=ctx.patient_language,
            target_lang=ctx.clinical_language,
        )

    return await _process_answer(ctx, answer_text)


@router.get("/{session_id}/qa-log", response_model=QALogResponse)
async def get_qa_log(session_id: str, user: dict = Depends(verify_token)) -> QALogResponse:
    ctx = await _get_session(session_id, user["sub"])
    return QALogResponse(
        qa_log=[e.model_dump(mode="json") for e in ctx.qa_log],
        flags=[f.model_dump(mode="json") for f in ctx.flags],
        raw_transcript=ctx.raw_transcript,
        translated_transcript=ctx.translated_transcript,
    )


@router.patch("/{session_id}/answer/{question_id}")
async def edit_answer(session_id: str, question_id: str, body: EditAnswerRequest, user: dict = Depends(verify_token)):
    ctx = await _get_session(session_id, user["sub"])
    for entry in ctx.qa_log:
        if entry.question_id == question_id:
            entry.answer = body.answer.strip()
            await session_store.update(ctx)
            return {"ok": True}
    raise HTTPException(status_code=404, detail="Answer not found.")


# ─────────────────────────────────────────────
# Pipeline — SSE streaming progress
# ─────────────────────────────────────────────


def _sse(event: str, data: Any) -> str:
    return f"data: {json.dumps({'event': event, **data})}\n\n"


async def _pipeline_generator(session_id: str, user_id: str) -> AsyncGenerator[str, None]:
    ctx = await session_store.get(session_id, user_id=user_id)
    if not ctx:
        yield _sse("error", {"message": "Session not found"})
        return

    if not ctx.raw_transcript.strip():
        yield _sse("error", {"message": "No transcript to process"})
        return

    try:
        # Step 1: Translate
        yield _sse("step", {"step": "translate", "status": "running", "label": "Detecting language & translating"})
        translator = TranslationService()
        if not ctx.patient_language:
            ctx.patient_language = await translator.detect_language(ctx.raw_transcript)
        if ctx.patient_language != ctx.clinical_language:
            ctx.translated_transcript = await translator.translate(
                ctx.raw_transcript,
                source_lang=ctx.patient_language,
                target_lang=ctx.clinical_language,
            )
        else:
            ctx.translated_transcript = ctx.raw_transcript
        await session_store.update(ctx)
        yield _sse("step", {"step": "translate", "status": "done", "label": "Language detected & translated"})

        # Step 2: Completeness + Summarize in parallel
        yield _sse("step", {"step": "completeness", "status": "running", "label": "Checking completeness"})
        yield _sse("step", {"step": "summarize", "status": "running", "label": "Generating clinical note (SOAP)"})

        engine = LLMHistoryEngine(ctx.specialty, language=ctx.patient_language)
        completeness_svc = CompletenessService()
        summarization_svc = SummarizationService()

        full_text = ctx.translated_transcript or ctx.raw_transcript
        _completeness_task = asyncio.create_task(completeness_svc.check(ctx, engine.get_required_fields()))
        _summary_task = asyncio.create_task(summarization_svc.summarize(full_text))
        _pending = {_completeness_task, _summary_task}
        while _pending:
            _done, _pending = await asyncio.wait(_pending, timeout=10.0)
            if _pending:
                yield ": keepalive\n\n"
        completeness_result = _completeness_task.result()
        summary_result = _summary_task.result()

        ctx.completeness_report = completeness_result
        ctx.current_stage = ConsultationStage.COMPLETENESS_CHECK
        ctx.summary = summary_result
        ctx.current_stage = ConsultationStage.SUMMARY
        await session_store.update(ctx)

        yield _sse("step", {"step": "completeness", "status": "done", "label": "Completeness checked"})
        yield _sse("step", {"step": "summarize", "status": "done", "label": "Clinical note generated"})

        # Step 3: Diagnose — keepalive every 10 s to prevent SSE connection timeout
        yield _sse("step", {"step": "diagnose", "status": "running", "label": "Running AI diagnosis"})
        diagnosis_svc = DiagnosisService()
        _diag_task = asyncio.create_task(diagnosis_svc.diagnose(ctx))
        while not _diag_task.done():
            try:
                await asyncio.wait_for(asyncio.shield(_diag_task), timeout=10.0)
            except asyncio.TimeoutError:
                yield ": keepalive\n\n"   # SSE comment; browser ignores but keeps TCP alive
        ctx.diagnosis = _diag_task.result()   # re-raises if the task threw
        ctx.current_stage = ConsultationStage.DIAGNOSIS
        await session_store.update(ctx)
        yield _sse("step", {"step": "diagnose", "status": "done", "label": "Diagnosis complete"})

        # Done — send results
        yield _sse("complete", {
            "note": ctx.summary,
            "diagnosis": ctx.diagnosis.model_dump(mode="json") if ctx.diagnosis else None,
        })

    except Exception as exc:
        log.error("pipeline failed for session %s: %s", session_id, exc, exc_info=True)
        yield _sse("error", {"message": "Something went wrong processing this consultation. Please try again."})


@router.get("/{session_id}/pipeline")
async def run_pipeline(session_id: str, user: dict = Depends(verify_ws_token)):
    return StreamingResponse(
        _pipeline_generator(session_id, user["sub"]),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/{session_id}/prescribe")
async def prescribe(session_id: str, body: PrescribeRequest, user: dict = Depends(verify_token)):
    ctx = await _get_session(session_id, user["sub"])
    svc = PrescriptionService()
    ctx.prescription = await svc.prescribe(ctx, body.confirmed_diagnosis)
    ctx.current_stage = ConsultationStage.PRESCRIPTION
    await session_store.update(ctx)
    return {"prescription": ctx.prescription.model_dump(mode="json")}


@router.post("/{session_id}/finalize")
async def finalize(session_id: str, user: dict = Depends(verify_token)):
    ctx = await _get_session(session_id, user["sub"])
    ctx.current_stage = ConsultationStage.FINALIZED
    await session_store.update(ctx)
    return ctx.model_dump(mode="json")


@router.post("/{session_id}/override")
async def doctor_override(session_id: str, body: OverrideRequest, user: dict = Depends(verify_token)):
    ctx = await _get_session(session_id, user["sub"])
    original = getattr(ctx, body.field, None)
    ctx.overrides.append(
        DoctorOverride(
            stage=ctx.current_stage,
            field=body.field,
            original_value=original,
            overridden_value=body.value,
            reason=body.reason,
        )
    )
    if hasattr(ctx, body.field):
        try:
            setattr(ctx, body.field, body.value)
        except ValidationError as exc:
            raise HTTPException(422, f"Invalid value for '{body.field}': {exc.errors()[0]['msg']}")
    await session_store.update(ctx)
    return {"overridden": body.field, "new_value": body.value}


# ─────────────────────────────────────────────
# Voice streaming — WebSocket, parallel R2 + STT
# ─────────────────────────────────────────────


@router.websocket("/{session_id}/voice-stream")
async def voice_stream(
    websocket: WebSocket,
    session_id: str,
    user: dict = Depends(verify_ws_token),
) -> None:
    """
    Binary audio chunks arrive from the browser while the user speaks.
    On "stop", we run R2 upload and Deepgram transcription concurrently,
    then immediately call the LLM. Total latency = max(upload, transcribe) + LLM.
    """
    await websocket.accept()

    ctx = await session_store.get(session_id, user_id=user["sub"])
    if not ctx:
        await websocket.send_json({"type": "error", "message": "Session not found"})
        await websocket.close(code=1008)
        return

    audio_chunks: list[bytes] = []
    mime_type = "audio/webm;codecs=opus"

    try:
        # Handshake: browser sends {type:"start", mime_type:"..."} first
        msg = await asyncio.wait_for(websocket.receive(), timeout=10.0)
        if msg.get("text"):
            data = json.loads(msg["text"])
            client_mime = data.get("mime_type", "")
            if isinstance(client_mime, str) and client_mime.lower().startswith("audio/"):
                mime_type = client_mime
        await websocket.send_json({"type": "ready"})

        # Stream audio chunks until browser sends {type:"stop"}
        bytes_total = 0
        chunk_count = 0
        while True:
            msg = await asyncio.wait_for(websocket.receive(), timeout=120.0)
            if msg["type"] == "websocket.disconnect":
                break
            if msg.get("bytes"):
                audio_chunks.append(msg["bytes"])
                bytes_total += len(msg["bytes"])
                chunk_count += 1
                if chunk_count % 20 == 0:
                    await websocket.send_json({"type": "ack", "bytes": bytes_total})
            elif msg.get("text"):
                data = json.loads(msg["text"])
                if data.get("type") == "stop":
                    break

    except (asyncio.TimeoutError, WebSocketDisconnect):
        pass
    except Exception as exc:
        log.error("voice-stream recording failed for session %s: %s", session_id, exc, exc_info=True)
        await websocket.send_json({"type": "error", "message": GENERIC_LLM_ERROR})
        return

    if not audio_chunks:
        await websocket.send_json({"type": "retry", "message": RETRY_UNCLEAR_MESSAGE})
        await websocket.close()
        return

    full_audio = b"".join(audio_chunks)
    await websocket.send_json({"type": "processing", "stage": "transcribing"})

    # Parallel: upload to R2 AND transcribe — audio already in memory, no wait
    r2_task = asyncio.create_task(r2.upload_audio(full_audio, session_id, mime_type=mime_type))
    stt_task = asyncio.create_task(transcribe_bytes(full_audio, mime_type, language=ctx.patient_language))

    results = await asyncio.gather(r2_task, stt_task, return_exceptions=True)
    r2_key, transcript = results

    if isinstance(transcript, Exception):
        log.error("voice-stream transcription failed for session %s: %s", session_id, transcript, exc_info=transcript)
        await websocket.send_json({"type": "retry", "message": RETRY_UNCLEAR_MESSAGE})
        await websocket.close()
        return

    if isinstance(r2_key, str):
        ctx.audio_keys.append(r2_key)

    await websocket.send_json({"type": "transcript", "text": transcript})

    # Translate if needed before LLM call
    if ctx.patient_language and ctx.patient_language != ctx.clinical_language:
        translator = TranslationService()
        answer_text = await translator.translate(
            transcript,
            source_lang=ctx.patient_language,
            target_lang=ctx.clinical_language,
        )
    else:
        answer_text = transcript

    if not is_valid_answer(answer_text):
        await websocket.send_json({"type": "retry", "message": RETRY_UNCLEAR_MESSAGE})
        await websocket.close()
        return

    # Stream question tokens over the same WS connection
    _record_answer(ctx, answer_text)

    engine = LLMHistoryEngine(ctx.specialty, language=ctx.patient_language)
    question_text = ""
    new_flags: list[ClinicalFlag] = []
    is_complete = False

    try:
        async for chunk in engine.next_turn_stream(ctx, answer_text):
            if isinstance(chunk, str):
                question_text += chunk
                await websocket.send_json({"type": "token", "text": chunk})
            elif isinstance(chunk, dict) and chunk.get("__done__"):
                is_complete = chunk["is_complete"]
                new_flags = chunk["new_flags"]
                question_text = chunk.get("question_text") or question_text.strip()
    except Exception as exc:
        log.error("voice-stream question generation failed for session %s: %s", session_id, exc, exc_info=True)
        await websocket.send_json({"type": "error", "message": GENERIC_LLM_ERROR})
        await websocket.close()
        return

    is_complete, next_q = _resolve_completion(ctx, is_complete, question_text)
    await session_store.update(ctx)

    await websocket.send_json({
        "type": "done",
        "transcript": transcript,
        "next_question": next_q,
        "history_complete": is_complete,
        "new_flags": [f.model_dump(mode="json") for f in new_flags],
    })
    await websocket.close()


@router.delete("/{session_id}")
async def end_session(session_id: str, user: dict = Depends(verify_token)):
    ctx = await _get_session(session_id, user["sub"])
    for audio_key in ctx.audio_keys:
        try:
            await r2.delete_audio(audio_key)
        except Exception as exc:
            log.warning("Failed to delete audio %s for session %s: %s", audio_key, session_id, exc)
    await session_store.delete(session_id)
    return {"deleted": session_id}
