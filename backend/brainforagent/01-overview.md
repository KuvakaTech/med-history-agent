# Overview

## Product

**kuvaka Clinical AI** bundles three clinical AI surfaces in one FastAPI backend:

1. **Questionnaire screener** — AI interviews patient before physician consult
2. **Cabin consult** — AI listens during doctor-led in-room consultation
3. **Hospital ticketing** — AI receptionist voice check-in at hospital reception (public, no login)

Doctors and hospital admins are users (JWT). Clinical patients and ticket patients are data.

Outputs are physician-support only — no diagnosis during screening; red-flag detection and override/audit trails preserved on clinical paths.

---

## Three product surfaces

| Surface | Package | API | Auth | Who leads | AI behaviour |
|---------|---------|-----|------|-----------|--------------|
| **Questionnaire** | `app/clinical/` | v1 | Doctor JWT | AI asks | Speaks (TTS), 7–10 turns → pipeline |
| **Cabin** | `app/cabin/` | v1 | Doctor JWT | Doctor + patient | Never speaks; transcribes + assists |
| **Ticketing** | `app/ticketing/` | v2 | **None** (patient) / hospital_admin JWT (admin) | AI receptionist | Speaks (TTS), triage + consultation voice call |

Ticketing and questionnaire both use AI-led voice interviews but differ in tenancy (hospital slug, phone-global patients), flow (triage → department → clinical history), and auth model.

---

## Top-level layout (`backend/`)

```
backend/
├── app/                    # FastAPI application
├── tests/                  # pytest (~237 test functions, offline)
├── brainforagent/          # This documentation set
├── pyproject.toml          # Poetry deps + pytest config
├── requirements.txt
├── Dockerfile              # uvicorn :8001
├── CLAUDE.md               # Agent coding rules
└── .env / .env.example
```

---

## `app/` module tree

```
app/
├── main.py                 # v1 + v2 routers, lifespan indexes, /health, /dev
├── api/
│   ├── v1/
│   │   ├── api.py
│   │   └── endpoints/      # consultation, cabin, patients, tts
│   └── v2/
│       ├── api.py
│       └── endpoints/      # ticketing (public), ticketing_admin, setup
├── auth/                   # JWT, refresh, roles: doctor | hospital_admin | super_admin
├── clinical/               # Questionnaire domain
├── cabin/                  # Doctor-led live consult
├── ticketing/              # Hospital check-in voice flow
│   ├── models.py
│   ├── hospital_store.py
│   ├── patient_store.py    # phone-global TicketPatient
│   ├── session_store.py    # TicketSession + TKT-000042 counter
│   ├── triage_engine.py    # Phase 1: max 3 turns, name/age/department
│   ├── consultation_engine.py  # Phase 2: 7–12 clinical questions
│   ├── voice_session.py      # TicketVoiceSession orchestrator
│   ├── deepgram_live.py      # Realtime STT (nova-3)
│   ├── tts_service.py        # Stock ElevenLabs voice (not clone)
│   └── events.py             # WS event type constants
├── agent/                  # llm, usage, transcription, tts, summarization
├── core/                   # config, database, ratelimit
├── storage/r2.py
└── static/                 # Dev harness (/dev when DEBUG or CABIN_TEST_HARNESS)
```

---

## MongoDB collections

| Collection | Domain | Model |
|------------|--------|-------|
| `sessions` | Questionnaire | `ConsultationContext` |
| `cabin_sessions` | Cabin | `CabinSession` |
| `cabin_leases` | Cabin WS dedup | lease docs |
| `patients` | Clinical patients | `Patient` (doctor-scoped) |
| `users` | Auth | user docs with `role` |
| `refresh_tokens` | Auth | hashed refresh (TTL) |
| `ticket_hospitals` | Ticketing | `Hospital` |
| `ticket_categories` | Ticketing | `TicketCategory` (per hospital) |
| `ticket_patients` | Ticketing | `TicketPatient` (phone globally unique) |
| `ticket_sessions` | Ticketing | `TicketSession` |
| `ticket_counters` | Ticketing | atomic `TKT-` number seq |

Indexes created in `main.py` lifespan.

---

## User roles

| Role | Created by | JWT claims | Access |
|------|------------|------------|--------|
| `doctor` | `/api/v1/auth/register` | `sub`, `role=doctor` | All v1 routes |
| `hospital_admin` | super_admin via `/api/v2/admin/users` | `sub`, `role`, `hospital_id` | v2 admin scoped to hospital |
| `super_admin` | setup or super_admin | `sub`, `role`, `hospital_id=null` | v2 admin all hospitals + create hospitals/users |

v1 `verify_token` accepts any valid JWT (doctor, hospital_admin, super_admin). v2 admin uses `require_hospital_admin` or `require_super_admin`.

---

## Dev harness

When `DEBUG=true` or `CABIN_TEST_HARNESS=true`, static files mount at `/dev` (cabin test pages). Never mount in production.

Ticketing frontend routes (from setup next_steps): `/checkin/{slug}/start`, `/admin`, `/login`.
