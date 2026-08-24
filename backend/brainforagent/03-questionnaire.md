# Questionnaire (AI-led screener)

**API:** v1 (`/api/v1/consultation`). **Auth:** doctor JWT.

Package: `app/clinical/` + `app/api/v1/endpoints/consultation.py`

## Purpose

An LLM interviews the patient before the physician consult. After 7–10 questions covering essential history areas, a pipeline produces translated transcript, completeness report, SOAP summary, differential diagnosis, and optional prescription.

---

## Core document: `ConsultationContext`

Defined in `app/clinical/context.py`. This **is** the session.

Key fields:

| Field | Role |
|-------|------|
| `session_id`, `specialty`, `current_stage` | Identity and workflow stage |
| `patient_name`, `patient_age`, `patient_gender`, `chief_complaint` | Intake demographics |
| `patient_language`, `clinical_language` | Translation target |
| `qa_log` | List of `QAEntry` (question_id, question_text, answer) |
| `current_question` | Active question text |
| `covered_areas` | LLM-judged topic coverage keys |
| `history_complete` | Screening finished |
| `raw_transcript`, `translated_transcript` | Pipeline inputs |
| `flags` | `ClinicalFlag` red-flag list |
| `completeness_report`, `summary`, `diagnosis`, `prescription` | Pipeline outputs |
| `overrides` | `DoctorOverride` audit trail |
| `audio_keys` | R2 keys for voice answers |
| `patient_id` | Optional link to `Patient` |
| `latitude`, `longitude` | Optional geolocation |

Enums: `Specialty` (general_medicine, psychotherapy, gynecology), `ConsultationStage` (questionnaire → finalized).

---

## History-taking engine

`app/clinical/questionnaire/engine.py` — `LLMHistoryEngine`

### Turn invariants

- `MIN_TURNS = 7`, `MAX_TURNS = 10`
- `turn_count == len(ctx.qa_log)`
- At `MAX_TURNS`: short-circuit `is_complete=True`, no LLM call
- Below `MIN_TURNS`: `is_complete` forced `False` unless every area covered

### Coverage

- `AREA_DESCRIPTIONS` — canonical keys: timeline, severity, character_location, modifying_factors, associated_symptoms, past_history, medications, allergies
- Coverage judged **by LLM each turn** (`covered_areas`) — never keyword-match transcript (breaks non-English)
- `_uncovered_areas()` returns only the **first** missing area → enforces one-question-per-turn

### LLM calls

- Visible question: `stream_complete` (fast=True) or `complete`
- Metadata: `complete_structured(NextTurnMeta)` — `is_complete`, `new_flags`, `covered_areas`

### Streaming path (`next_turn_stream`)

Two concurrent LLM calls:

1. `stream_complete` — question tokens to patient
2. `complete_structured(NextTurnMeta)` — completion metadata

Yields `str` tokens, then terminal `{"__done__": True, ...}` dict. Callers must handle both shapes.

---

## Shared transport helpers

In `consultation.py` — three transports must stay aligned:

| Helper | Role |
|--------|------|
| `_record_answer` | Append answer to `qa_log` |
| `_resolve_completion` | Apply engine completion state |
| `_process_answer` | Sync JSON path |
| `_stream_answer_generator` | SSE path |

Transports:

1. `POST /answer` — sync JSON
2. `POST /answer-stream` — SSE
3. `WS /voice-stream` — live voice (STT + engine)

Changes to turn handling usually belong in these helpers + `engine.py`, not one transport alone.

---

## Clinical pipeline

`GET /{session_id}/pipeline` — SSE (`verify_ws_token` for EventSource)

Sequence:

```
translate → (completeness ‖ summarize, parallel) → diagnose → complete
```

- Long steps emit `: keepalive\n\n` SSE comments every 10s
- Response header: `X-Accel-Buffering: no`
- Services: `translation.py`, `completeness.py`, `summarization/service.py`, `diagnosis.py`

Separate POSTs (not in pipeline SSE):

- `POST /prescribe` — `prescription.py`
- `POST /finalize` — mark finalized
- `POST /override` — doctor field override with audit

---

## Voice answer path

`POST /answer-audio` and WS `voice-stream`:

1. Upload audio to R2 (concurrent with STT via `asyncio.gather`)
2. Deepgram STT (`nova-3`); non-English → `language=multi` for Hindi/English code-switch
3. Engine next turn

TTS for questions: `app/agent/tts/service.py` — ElevenLabs cloned voice if configured, else Deepgram Aura.

---

## Session store

`app/clinical/session_store.py` — collection `sessions`

- Mongo-first on read (always, even if write latch tripped)
- Write-through in-memory `_mem`
- `_mongo_write_failed` latch stops write retries after first failure
- `user_id` stored on doc but not in model — in-memory update preserves non-model keys
- Updates use `$set` only model fields — `user_id` untouched in Mongo

`DELETE /consultation/{id}` deletes session and stored audio from R2.

---

## Clinical safety prompts

Engine system prompt enforces:

- One question, one topic per turn
- Never diagnose or suggest treatments during screening
- Red-flag detection every answer (CRITICAL_RED_FLAG, RED_FLAG, etc.)
- Never repeat already-asked topics

Preserve these when editing prompts or engine logic.
