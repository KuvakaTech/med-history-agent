# Backend Brain — Index

Agent-oriented documentation for the kuvaka Clinical AI FastAPI backend (`backend/`).

**Repo root:** `med-history-agent/` (parent of `backend/`). Also contains `frontend/` (Next.js 14) and `docker-compose.yml`.

**Last reviewed:** August 2026

---

## Documents

| File | Contents |
|------|----------|
| [01-overview.md](01-overview.md) | Three product surfaces, directory layout, module tree |
| [02-architecture.md](02-architecture.md) | Request layers, v1 + v2 routing, auth roles, conventions |
| [03-questionnaire.md](03-questionnaire.md) | AI-led screener (v1): engine, pipeline, transports |
| [04-cabin.md](04-cabin.md) | Doctor-led cabin (v1): live session, analysis, leases, gaps |
| [05-api-endpoints.md](05-api-endpoints.md) | Full v1 + v2 HTTP/WebSocket route inventory |
| [06-persistence-auth.md](06-persistence-auth.md) | MongoDB stores, JWT roles, multi-tenancy |
| [07-llm-external-services.md](07-llm-external-services.md) | LLM facade, STT/TTS (clinical vs ticketing), R2 |
| [08-config-settings.md](08-config-settings.md) | Environment variables and tuning knobs |
| [09-testing-status-roadmap.md](09-testing-status-roadmap.md) | Test suite (~237 tests), touch-points |
| [10-ticketing.md](10-ticketing.md) | Hospital check-in voice flow (v2): triage, consultation, voice WS |

---

## Quick orientation

```
Three products, one FastAPI app:

  AI-led screener     app/clinical/      v1  Doctor JWT — patient interviewed by LLM (7–10 Qs)
  Doctor-led cabin    app/cabin/         v1  Doctor JWT — doctor talks; AI listens only
  Hospital ticketing  app/ticketing/     v2  Public voice check-in + hospital admin dashboard

Request paths:
  /api/v1  → auth | patients | consultation | note | cabin
  /api/v2  → /t/{slug}/... (public) | /admin/... (hospital_admin) | /setup (bootstrap)

Session documents:
  ConsultationContext   questionnaire (sessions)
  CabinSession          cabin consults (cabin_sessions)
  TicketSession         hospital check-in (ticket_sessions)
  Patient               doctor-scoped patients (patients)
  TicketPatient         phone-global ticketing patients (ticket_patients)

Auth roles (JWT claim `role`):
  doctor           v1 clinical/cabin — default on register
  hospital_admin   v2 admin — scoped to hospital_id in JWT
  super_admin      v2 admin — all hospitals; creates hospitals/admins

LLM:
  Always via app/agent/llm.py — never call provider SDKs from services
  Fallback: Anthropic → Groq → Gemini
```

---

## Commands (from `backend/`)

```bash
pip install -e .
uvicorn app.main:app --reload --port 8001
ruff check .
pytest
```

Config: `backend/.env` (copy from `.env.example`). `ENV=<path>` overrides env file.

---

## Agent guidance

- `CLAUDE.md` — coding rules for this backend (read before making changes)
