# Cabin (doctor-led consult)

**API:** v1 (`/api/v1/cabin`). **Auth:** doctor JWT.

Package: `app/cabin/` + `app/api/v1/endpoints/cabin.py`

## Purpose

Doctor and patient (plus optional attendee) talk normally. A screen facing the doctor shows:

- **Left pane** — live transcript + AI suggestions (questions to ask, differentials, tests, red flags)
- **Right pane** — structured clinical panel (symptoms, diagnoses, tests, medications, questions asked)

The AI **never speaks** in cabin mode.

---

## Core document: `CabinSession`

`app/cabin/models.py` — no `validate_assignment` (teardown safety).

Key fields:

| Field | Role |
|-------|------|
| `session_id`, `doctor_id`, `patient_id` | Identity + tenancy |
| `utterances` | `Utterance` list (seq, text, role, timestamps) |
| `panel` | `ClinicalPanel` — five headings |
| `suggestions` | `LiveSuggestions` — left pane |
| `status` | Connection: `active` \| `ended` \| `interrupted` |
| `workflow` | Clinical: `draft` → `coded` → … → `submitted` |
| `consent_captured_at` | Required before audio |
| `audio_key` | R2 WAV after end |
| `roles_verified` | Role attribution state |
| `cost` | `SessionCost` — LLM token spend |
| `overrides` | `CabinOverride` audit on ended records |

`UtteranceRole`: doctor, patient, attendee, unknown.

---

## Package files

| File | Responsibility |
|------|----------------|
| `models.py` | Pydantic schemas only |
| `store.py` | `cabin_sessions` — same Mongo+mem pattern as questionnaire, **separate latch** |
| `scribe.py` | `ScribeStream` — ElevenLabs Scribe v2 Realtime WS client |
| `analysis.py` | `attribute_roles`, `extract_panel_delta`, `merge_panel_delta`, `reconcile_panel`, `suggest` |
| `live.py` | `CabinLiveSession` — orchestrator (~850 lines) |
| `postprocess.py` | `rediarize()` — batch diarization on stored record |
| `leases.py` | Mongo lease for cross-worker duplicate WS prevention |
| `gaps.py` | `detect_gaps()` — patient history vs panel (live alerts) |

Supporting:

- `app/agent/usage.py` — contextvars cost sink for cabin LLM calls
- `app/clinical/profile.py` — `build_profile()` merges doctor-asserted + derived conditions

---

## Live session orchestrator

`CabinLiveSession` in `live.py` — four concurrent asyncio tasks, `FIRST_COMPLETED` teardown:

| Task | Role |
|------|------|
| `_recv_client` | Browser WS — audio PCM + control frames |
| `_pump_to_scribe` | Audio queue → ElevenLabs socket |
| `_recv_scribe` | EL events → utterances → trigger analysis |
| `_analysis_loop` | Debounced roles, gated panel/suggest, gap alerts, persist, lease renew |

Rules:

- **Partials never touch the LLM** — only committed utterances
- Audio spooled to temp WAV on disk → streamed to R2 on end (`upload_fileobj`)
- Analysis cadence gated by `CABIN_PANEL_MIN_INTERVAL_SECS`, `CABIN_MIN_NEW_WORDS_FOR_ANALYSIS`

---

## STT: ElevenLabs Scribe v2 Realtime

Why not Deepgram for cabin: `nova-3` multilingual excludes Marathi and Gujarati.

`scribe.py` — `ScribeStream`:

- Connect, handshake, `send_audio()`, `events()`
- Error classification, reconnect + planned cutover (`CABIN_STT_ROLLING_RECONNECT_SECS`)
- Knows nothing clinical

**Security:** Backend relays audio — browser never talks to ElevenLabs directly. Prevents client-authored transcript injection into medical record.

Config: `ELEVENLABS_STT_WS_URL`, `ELEVENLABS_STT_MODEL`, `CABIN_STT_SECONDARY_LANGUAGES` (hin,eng,mar,guj).

---

## Analysis loop

`analysis.py`:

1. **Role attribution** — LLM labels utterances doctor/patient/attendee (`attribute_roles`)
2. **Panel delta** — small structured extract per pass (`extract_panel_delta` + `merge_panel_delta`)
3. **Periodic reconcile** — full panel pass every `CABIN_PANEL_RECONCILE_EVERY_N_PASSES` (`reconcile_panel`)
4. **Suggestions** — questions, differentials, tests, red flags (`suggest`)

Deltas keep UI responsive but cannot drop earlier entries — reconcile fixes corrections/retractions.

---

## Gap alerts (Phase 2a)

`gaps.py` — `detect_gaps(panel, profile)`:

- Compares `PatientProfile` (conditions, meds, allergies) vs `panel.questions_asked`
- Runs on longer cadence than panel (`CABIN_GAP_MIN_INTERVAL_SECS`)
- Skipped if patient has no history
- Hard ceiling `CABIN_GAP_MAX_PASSES` per session
- Emits `gap_alert` on WebSocket wire

---

## Post-consult

On session end:

1. Upload spooled WAV to R2 (if `CABIN_ARCHIVE_AUDIO`)
2. Optional `rediarize()` batch pass (`CABIN_REDIARIZE_ON_END`) — corrects speaker labels on stored record
3. `status = ended`, persist final state

`GET /{id}/record` — full ended record (utterances, panel, suggestions, overrides).

`POST /{id}/override` — doctor corrections on ended record (409 if still active).

---

## Cross-worker lease

`leases.py` — `cabin_leases` collection:

- `_id` = `session_id` — primary key decides acquire race
- TTL index on `expires_at` (hygiene for crashed workers)
- Renewed from analysis loop (`CABIN_LEASE_RENEW_SECS`)
- **Fails open** — Mongo outage degrades to per-process guard, not lockout

Concurrent cap: `CABIN_MAX_CONCURRENT_SESSIONS_PER_DOCTOR` (default 3) — refused with `close(4029)`.

---

## Cabin store

`app/cabin/store.py` — collection `cabin_sessions`

- Same Mongo-first read + mem write-through + separate `_mongo_write_failed` latch
- `list_for_doctor` / `list_for_patient` use summary projection (no utterances/suggestions)
- Scoped by `doctor_id` on every read

---

## Phase 0 blocker

Live ElevenLabs validation not done from dev machine:

- Marathi/Gujarati usability
- Mid-stream language switching
- Session time limits
- ISO 639-1 vs 639-3 language codes

See `docs/02-roadmap.md` and `docs/01-what-was-built.md`.
