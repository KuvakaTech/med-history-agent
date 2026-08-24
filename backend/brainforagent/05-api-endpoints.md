# API Endpoints

## v1 — `/api/v1`

Base: `settings.API_V1_STR` (default `/api/v1`). Doctor JWT on all routes except auth register/login.

### Auth — `/api/v1/auth`

| Method | Path | Auth | Purpose |
|--------|------|------|---------|
| POST | `/register` | None | Create doctor account (`role=doctor`) |
| POST | `/login` | None | Login |
| POST | `/refresh` | Cookie/body | Rotate refresh token |
| POST | `/logout` | Cookie/body | Invalidate refresh |

JWT includes `role` (default `doctor`). Access 15 min; refresh 7 days hashed in Mongo.

### Patients — `/api/v1/patients`

| Method | Path | Purpose |
|--------|------|---------|
| POST | `` | Create patient |
| GET | `` | List for doctor |
| GET | `/{patient_id}` | Get |
| GET | `/{patient_id}/history` | Questionnaire + cabin sessions |
| PATCH | `/{patient_id}` | Update incl. clinical profile |

### Consultation — `/api/v1/consultation`

| Method | Path | Auth dep | Purpose |
|--------|------|----------|---------|
| POST | `/start` | verify_token | New session + opening Q |
| GET | `/{session_id}` | verify_token | State |
| POST | `/{session_id}/answer` | verify_token | Text answer (sync) |
| POST | `/{session_id}/answer-stream` | verify_token | SSE answer |
| POST | `/{session_id}/answer-audio` | verify_token | Voice answer |
| GET | `/{session_id}/qa-log` | verify_token | Q&A log |
| PATCH | `/{session_id}/answer/{question_id}` | verify_token | Edit answer |
| GET | `/{session_id}/pipeline` | **verify_ws_token** | SSE pipeline |
| POST | `/{session_id}/prescribe` | verify_token | Prescription |
| POST | `/{session_id}/finalize` | verify_token | Finalize |
| POST | `/{session_id}/override` | verify_token | Doctor override |
| WS | `/{session_id}/voice-stream` | verify_ws_token | Live voice |
| DELETE | `/{session_id}` | verify_token | Delete + audio |

### TTS — `/api/v1/note`

| Method | Path | Purpose |
|--------|------|---------|
| POST | `/speak` | TTS for note text |

### Cabin — `/api/v1/cabin`

| Method | Path | Auth dep | Purpose |
|--------|------|----------|---------|
| POST | `/` | verify_token | Create (consent required) |
| GET | `/` | verify_token | List summary |
| GET | `/{session_id}` | verify_token | Live summary |
| GET | `/{session_id}/record` | verify_token | Full ended record |
| POST | `/{session_id}/override` | verify_token | Override ended (409 if active) |
| DELETE | `/{session_id}` | verify_token | Delete + audio |
| WS | `/{session_id}/stream` | verify_ws_token | Live audio + analysis |

---

## v2 — `/api/v2`

### Setup (optional) — `/api/v2/setup`

Only registered when `ENABLE_SETUP_ENDPOINT=true` (default **false**).

| Method | Path | Auth | Purpose |
|--------|------|------|---------|
| POST | `/setup` | Body `secret` = `JWT_SECRET_KEY` | Bootstrap hospital + super_admin |

Idempotent. After first hospital exists, use admin endpoints instead.

### Public ticketing — `/api/v2/t`

**No authentication.** Hospital identified by URL slug.

| Method | Path | Purpose |
|--------|------|---------|
| POST | `/{slug}/session` | Create session (phone required); returns `ticket_number` |
| GET | `/{slug}/session/{id}/result` | SOAP summary, flags, IST timestamps |
| POST | `/{slug}/session/{id}/discard` | Soft-delete session |
| WS | `/{slug}/session/{id}/voice` | Continuous voice call (triage + consultation) |

**Start session body:** `phone`, optional `language`, `gender` (default `unknown`).

### Admin — `/api/v2/admin`

Requires `require_hospital_admin` (or `super_admin`). Super_admin scopes via `?hospital_id=`.

| Method | Path | Role | Purpose |
|--------|------|------|---------|
| GET | `/hospitals` | super_admin | List hospitals |
| POST | `/hospitals` | super_admin | Create hospital (+ seed 15 categories) |
| GET | `/users` | super_admin | List admin accounts |
| POST | `/users` | super_admin | Create hospital_admin or super_admin |
| GET | `/stats` | hospital_admin | Dashboard stats (today + all-time) |
| GET | `/sessions` | hospital_admin | List with filters |
| GET | `/sessions/{id}` | hospital_admin | Full session detail |
| GET | `/categories` | hospital_admin | List departments |
| POST | `/categories` | hospital_admin | Create department |
| PATCH | `/categories/{id}` | hospital_admin | Update label/active |

**Session list filters:** `status`, `category`, `ticket`, `phone`, `date_from`, `date_to`, `include_deleted`, `limit`.

---

## App root

| Method | Path | Auth | Purpose |
|--------|------|------|---------|
| GET | `/health` | None | `{"status":"ok","version":"..."}` |
| GET | `/dev/*` | None | Static harness (DEBUG or CABIN_TEST_HARNESS) |

---

## Auth header vs query token

| Transport | Pattern |
|-----------|---------|
| HTTP | `Authorization: Bearer <jwt>` |
| EventSource / WebSocket (v1) | `?token=<jwt>` |

Ticketing public WS has **no token** — session_id in URL is the capability.
