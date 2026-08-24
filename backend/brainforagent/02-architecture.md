# Architecture

## Request layers

```
HTTP/WS request
    ↓
app/main.py
    ├── CORS (credentials-aware; regex when allow-all)
    ├── SlowAPI rate limiting (IP: CF-Connecting-IP → X-Forwarded-For → peer)
    ├── Catch-all 500 handler (manual CORS headers)
    ├── api_router at /api/v1
    └── api_v2_router at /api/v2
            ↓
v1: auth | patients | consultation | note | cabin
v2: /t/{slug}/... (public) | /admin/... (JWT) | /setup (optional bootstrap)
            ↓
    endpoints → domain packages + agent/*
            ↓
    MongoDB (Motor) + in-memory fallback (sessions, cabin, ticketing stores)
```

---

## v1 routing

`app/api/v1/api.py`:

```python
api_router.include_router(auth_router.router, prefix="/auth")
api_router.include_router(patients.router)
api_router.include_router(consultation.router, prefix="/consultation")
api_router.include_router(tts.router, prefix="/note")
api_router.include_router(cabin.router, prefix="/cabin")
```

`main.py`: `app.include_router(api_router, prefix=settings.API_V1_STR)` → `/api/v1`

---

## v2 routing

`app/api/v2/api.py`:

```python
# Gated: settings.ENABLE_SETUP_ENDPOINT (default False)
api_v2_router.include_router(setup_router)           # POST /api/v2/setup

api_v2_router.include_router(ticketing_router, prefix="/t")      # public patient
api_v2_router.include_router(admin_router, prefix="/admin")    # hospital admin
```

`main.py`: `app.include_router(api_v2_router, prefix="/api/v2")`

Public ticketing routes require **no auth** — hospital identified by URL slug (`/t/aiims/session`).

---

## Auth dependencies (`app/auth/deps.py`)

| Dependency | Used for | Token |
|------------|----------|-------|
| `verify_token` | v1 HTTP | `Authorization: Bearer` |
| `verify_ws_token` | v1 SSE/WS | `?token=` |
| `require_hospital_admin` | v2 admin | Bearer; `role` in `hospital_admin`, `super_admin` |
| `require_super_admin` | v2 super routes | Bearer; `role == super_admin` |

JWT payload includes: `sub`, `email`, `name`, `role`, `hospital_id` (admin only), `iat`, `exp`.

`HTTPBearer(auto_error=False)` — missing header returns 401 (not 403).

---

## Session mutation patterns

**Questionnaire:** load `ConsultationContext` → mutate → `session_store.update(ctx)`. `validate_assignment=True` on model.

**Cabin:** load `CabinSession` → mutate → `cabin_session_store.update(session)`.

**Ticketing:** load `TicketSession` → mutate → `ticket_session_store.update(session)`. Voice session drives most updates.

---

## Error handling contract

- Provider errors (LLM, STT, TTS) must not reach end users on patient-facing paths
- Endpoints log with `exc_info=True`
- SSE/WS emit generic module-level messages
- Catch-all in `main.py` attaches CORS manually (ServerErrorMiddleware sits outside CORSMiddleware)

---

## Rate limiting

- From `settings` only — never hardcode in decorators
- SlowAPI keys on IP
- WebSocket routes not covered — cabin uses concurrent session cap; ticketing has no WS rate limit

---

## Code conventions

- `from __future__ import annotations`
- Type hints on public functions; Pydantic for all request/response models
- Async throughout; boto3 in `run_in_executor`
- Prompts as module-level constants next to the service
- LLM only via `app/agent/llm.py`: `complete`, `complete_structured`, `stream_complete`

---

## Multi-tenancy

| Domain | Scope key | Cross-tenant response |
|--------|-----------|----------------------|
| Questionnaire | `user_id` (JWT `sub`) | 404 |
| Cabin | `doctor_id` | 404 |
| Clinical patients | `doctor_id` | 404 |
| Ticketing sessions | `hospital_id` (from slug or JWT) | 404 |
| Ticket patients | phone global — **not** hospital-scoped | N/A |

Ticketing admin: `hospital_admin` always scoped via JWT `hospital_id`; `super_admin` passes `?hospital_id=` or omits for cross-hospital session lookup.

---

## Lifespan

`main.py` creates indexes for all collections including ticketing (`ticket_hospitals`, `ticket_categories`, `ticket_patients`, `ticket_sessions`, `ticket_counters`).
