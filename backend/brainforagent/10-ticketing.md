# Ticketing (hospital voice check-in)

**API:** v2 (`/api/v2/t/{slug}/...`). **Auth:** none for patients; `hospital_admin` / `super_admin` for `/admin`.

Package: `app/ticketing/` + `app/api/v2/endpoints/`

## Purpose

AI receptionist at hospital reception. Patient scans QR or opens check-in URL, enters phone, then has a **continuous voice call** with the AI:

1. **Triage** (≤3 turns) — name, age, infer department from reason for visit
2. **Consultation** (7–12 turns) — clinical history for that department (same areas as questionnaire screener)
3. **Result** — SOAP summary + flags; human-readable `ticket_number` as receipt

Default language: Hindi (`hi`). Hospital identified by URL slug (e.g. `aiims`).

---

## Core models (`ticketing/models.py`)

### `Hospital`

- `hospital_id`, `slug` (unique URL key), `name`, `default_language` (default `hi`)

### `TicketCategory`

- Per-hospital departments; 15 seeded on hospital create (`DEFAULT_CATEGORIES`)
- `key` (e.g. `gynecology`), `label`, `active`

### `TicketPatient`

- **Phone globally unique** — same person at two hospitals shares one record
- `name`, `age`, `gender` — updated via upsert when collected (never erased by null)

### `TicketSession`

| Field | Role |
|-------|------|
| `session_id` | UUID |
| `ticket_number` | `TKT-000042` — atomic counter |
| `hospital_id`, `patient_id` | Tenancy |
| `phase` | `triage` → `consultation` → `result` |
| `status` | `active` → `completed` or `partial` |
| `deleted_at` | Soft delete |
| `category` | `CategoryInfo` (key, label, source: `auto` \| `manual`) |
| `language`, `gender` | Session context |
| `qa_log` | `TicketQAEntry[]` |
| `flags` | `TicketFlag[]` |
| `summary` | SOAP dict from `SummarizationService` |
| `transcript` | `TicketTranscriptEntry[]` — raw Gemini Live turns (V2). Additive default. |
| `turn_count` | Total Q&A turns (V2: incremented on each final user transcript; overwritten with `len(qa_log)` post-call) |
| `started_at`, `ended_at`, `updated_at` | UTC stored; IST at API boundary |

**Stale rule:** `active` + no update for 30 min → lazily set `partial` on read.

---

## Voice orchestrator (`TicketVoiceSession`)

`ticketing/voice_session.py` — one WebSocket session.

### Per-turn loop

1. Patient speaks → Deepgram streams interim text (`partial_transcript`)
2. `UtteranceEnd` → final transcript assembled
3. LLM turn (triage or consultation engine)
4. LLM streams question → TTS (MP3) → `agent_speaking` with `audio_b64`
5. `agent_done_speaking` → **mic gate opens** (no barge-in)

### Client → Server WS messages

| Type | Purpose |
|------|---------|
| binary | PCM16 16kHz (only while mic gate open) |
| `start` | Handshake after connect |
| `stop` | Graceful end |
| `category_selected` | Manual department pick |
| `ping` | Keepalive |

### Server → Client (see also `events.py`)

| Type | When |
|------|------|
| `ready` | Deepgram connected |
| `triage_started` | Phase 1 begins |
| `category_identified` | Auto department guess |
| `category_manual_required` | Could not infer — FE shows picker |
| `category_confirmed` | Manual or auto confirmed |
| `consultation_started` | Phase 2 begins |
| `partial_transcript` | Live STT |
| `agent_speaking` | TTS audio + question text |
| `agent_done_speaking` | Mic opens |
| `red_flag_raised` | Urgent flag during consultation |
| `consultation_ended` | Clinical questions done |
| `result_ready` | SOAP + flags |
| `session_partial` | No transcript to summarize |
| `error` | Optional `fatal: true` |
| `ended` | Session over |

All server messages include `ts` timestamp.

### Silence handling

- Nudge after 8s (`silence_nudge`)
- Timeout after 20s
- Max 2 retries re-asking same question before giving up

---

## Triage engine (`triage_engine.py`)

- `MAX_TRIAGE_TURNS = 3`
- Extracts: name, age, department (`category_guess` against hospital categories)
- Same pattern as questionnaire: `stream_complete` + `complete_structured(TriageMeta)` concurrent
- Opening: warm greeting + ask name
- **Does not** ask "which department?" — infers from symptoms
- Early exit when name + age + category known, or forced at turn 3
- **Server-side verification** of completion — does not trust LLM `is_complete` alone
- If no category after 3 turns: `category_manual_required` → wait for `category_selected`

Updates `TicketPatient` name/age when extracted.

---

## Consultation engine (`consultation_engine.py`)

- `MIN_CONSULTATION_TURNS = 7`, `MAX_CONSULTATION_TURNS = 12`
- Category-aware system prompt (department from triage)
- Chief complaint may come from triage — passed to avoid re-asking
- 8 required clinical areas (complaint, timeline, severity, character, modifiers, associated, past history, meds/allergies)
- Red flags every turn — **no diagnosis, completeness, or prescription**
- `covered_areas` tracked server-side in `_consult_covered`
- Respects early `is_complete` from meta (with MIN floor)

---

## Finalize

`_finalize()` in `voice_session.py`:

1. Build transcript from `qa_log`
2. Empty transcript → `status=partial`, `session_partial` event
3. Else `SummarizationService.summarize()` → SOAP dict
4. `status=completed`, `ended_at` set
5. `result_ready` event with summary + flags

Patient fetches same data via `GET /t/{slug}/session/{id}/result` (IST timestamps).

---

## Voice V2 — Gemini Live (`TICKETING_USE_GEMINI_LIVE`)

Same WS URL. `voice_stream` in `app/api/v2/endpoints/ticketing.py` dispatches on `settings.TICKETING_USE_GEMINI_LIVE` (default **false** → V1 unchanged).

When true, `TicketVoiceSessionV2` (`ticketing/voice_session_v2.py`) talks to Gemini Live via `ticketing/gemini_live.py` (direct `google-genai`, **no VideoSDK**). Frontend branches once on `ready.voice_mode === "gemini_live"`.

### Conversation model vs V1

| | V1 (`TicketVoiceSession`) | V2 (`TicketVoiceSessionV2`) |
|--|---------------------------|-----------------------------|
| Speech | Deepgram live STT + ElevenLabs/Deepgram TTS | Gemini Live speech-in / speech-out |
| Turns | Server-gated: mic closed until `agent_done_speaking` | Continuous duplex; user can barge in |
| VAD | Deepgram UtteranceEnd 1000ms | Gemini server VAD, 400ms end-of-speech |
| Silence retry | Re-asks the same question (repeat loop) | Not implemented — Gemini VAD only |
| During-call LLM | Haiku per turn | None except tool calls + optional triage-ceiling Haiku fallback |
| Flags during call | `red_flag_raised` live | **Post-call only** (live banner stays empty) |
| Report | SOAP from `qa_log` | Claude extract of raw `transcript` → `qa_log` / flags / SOAP |

### Phase control — function calling

Triage Live session is created with `finish_triage(patient_name, patient_age, routing_summary, category_key, confidence)`.

- Valid hospital `category_key` + confidence `high`/`medium` → `category_identified` (`source: auto`) → reconnect specialty session with `routing_summary` in the system instruction.
- Invalid key, `low` confidence, or tool never fires after 3 user transcripts → Haiku structured extract (`extract_triage_fallback`); if that also fails → `category_manual_required` (picker; audio relay paused).
- Specialty session tools: `finish_consultation(reason)`. 12 user-transcript ceiling force-ends the phase.

The patient is **never** asked which department. Category keys are internal, injected into the triage system instruction only (`ticketing/prompts_v2.py`).

Specialty prompt receives name, age, gender, `routing_summary` and must not re-ask the chief complaint.

Tool responses go back via `session.send_tool_response` (Gemini Developer API requires `FunctionResponse.id`).

### Caps

| Setting | Default | Role |
|---------|---------|------|
| `TICKETING_USE_GEMINI_LIVE` | `false` | Orchestrator switch |
| `GEMINI_LIVE_MODEL` | `gemini-2.5-flash-native-audio-preview-12-2025` | Live model id |
| `GEMINI_LIVE_VOICE` | `Puck` | Gemini prebuilt voice |
| `TICKETING_POST_CALL_MODEL` | empty → `ANTHROPIC_MODEL` | Documented; extract uses `complete_structured(fast=False)` |
| `TICKETING_MAX_SESSION_MINUTES` | `15` | Watchdog; graceful close then post-call extract |
| `TICKETING_MAX_CONCURRENT_LIVE_SESSIONS_PER_HOSPITAL` | `5` | In-process slot at WS accept; over-limit close 1013 |
| `TICKETING_PERSIST_INTERVAL_SECS` | `15.0` | Flush transcript to Mongo during the call |

Language: `TicketSession.language` (`hi`/`en`/`mr`/…) maps to BCP-47 in `gemini_live.bcp47_language` (default `hi-IN`). No global `GEMINI_LIVE_LANGUAGE`.

### Echo

Browser: `echoCancellation` + `noiseSuppression` + `autoGainControl`; agent PCM plays through the **same** `AudioContext` as capture. Frontend and server drop low-RMS frames while agent audio is playing.

### Post-call extract (`post_call_extract.py`)

1. Format `session.transcript` (Agent/Patient lines)
2. Empty → `status=partial`, `session_partial`
3. Else Claude `PostCallExtract` (name, age, category, flags, reconstructed `qa_log`) + `SummarizationService` SOAP
4. Persist session + `TicketPatient` name/age
5. `result_ready`

---

## Frontend integration notes

- WS URL: `/api/v2/t/{slug}/session/{session_id}/voice`
- Send `{"type":"start"}` after connect
- **V1 / `voice_mode` absent or `legacy`:** only send audio after `agent_done_speaking`; play MP3 from `agent_speaking`
- **V2 / `voice_mode=gemini_live`:** open mic on `ready`; stream PCM16 16kHz continuously; play `agent_audio_chunk` (PCM 24kHz); `interrupt` stops playback immediately
- Handle `category_manual_required` — show department picker, send `category_selected`
- V2 does not emit `red_flag_raised` during the call; flags appear on the result page
- Ignore unknown `type` values for forward compatibility

---

## Stores

| Store | Collection | Notes |
|-------|------------|-------|
| `hospital_store` | `ticket_hospitals`, `ticket_categories` | Seeds categories on create |
| `ticket_patient_store` | `ticket_patients` | Phone upsert |
| `ticket_session_store` | `ticket_sessions`, `ticket_counters` | TKT counter, stale flip, soft delete |

All three use Mongo + mem fallback with `_mongo_write_failed` latch.

---

## Admin API (`ticketing_admin.py`)

Scoped by JWT `hospital_id` or super_admin `?hospital_id=`.

- **Stats:** today's sessions by status + critical flag counts (IST date boundary)
- **Sessions list:** filter by status, category, ticket number, phone, date range
- **Session detail:** full doc + patient info + IST fields
- **Categories:** CRUD departments
- **Users** (super_admin): create `hospital_admin` / `super_admin`

Cross-hospital access for `hospital_admin` → 404.

---

## Bootstrap (`setup.py`)

`POST /api/v2/setup` when `ENABLE_SETUP_ENDPOINT=true`:

- Body `secret` must equal `JWT_SECRET_KEY`
- Creates hospital + seeds categories + super_admin
- Idempotent

Prefer `POST /api/v2/admin/hospitals` + `POST /api/v2/admin/users` after first bootstrap.

---

## Differences from v1 questionnaire

| Aspect | Questionnaire (v1) | Ticketing (v2) |
|--------|-------------------|----------------|
| Auth | Doctor JWT | Public (phone only) |
| Tenancy | Doctor `user_id` | Hospital `slug` |
| Patient ID | Optional clinical `Patient` | Phone-global `TicketPatient` |
| Phases | Single questionnaire | Triage → consultation → result |
| Turn limits | 7–10 total | 3 triage + 7–12 consult |
| STT | Deepgram batch/upload | Deepgram live (V1 voice) or Gemini Live (when `TICKETING_USE_GEMINI_LIVE`) |
| TTS voice | Cloned ElevenLabs if set | Stock ElevenLabs Adam (V1); Gemini voice (V2) |
| Receipt | `session_id` | `ticket_number` TKT-xxx |
| Pipeline | translate → diagnose → Rx | Summarize only (V2: Claude post-call extract) |
| Department | Specialty enum at start | LLM-inferred or manual pick |
