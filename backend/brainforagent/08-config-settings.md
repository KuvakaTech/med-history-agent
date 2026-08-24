# Configuration & Settings

`app/core/config.py` — env from `backend/.env` or `ENV=<path>`.

---

## Application

| Variable | Default |
|----------|---------|
| `PROJECT_NAME` | kuvaka Clinical AI |
| `API_V1_STR` | `/api/v1` |
| `VERSION` | `1.0.0` |
| `DEBUG` | `false` |
| `HOST` | `0.0.0.0` |
| `PORT` | `8001` |
| `ENABLE_SETUP_ENDPOINT` | **`false`** — gates `/api/v2/setup` |

---

## CORS

| Variable | Default |
|----------|---------|
| `BACKEND_CORS_ORIGINS` | `[]` |
| `BACKEND_CORS_ALLOW_ALL` | `false` |

---

## MongoDB / R2 / LLM / Auth / Rate limits

See prior sections — unchanged from v1:

- `MONGODB_URI`, `MONGODB_DB`
- `R2_*` keys
- `ANTHROPIC_*`, `GROQ_*`, `GOOGLE_API_KEY`, `GEMINI_*`
- `JWT_SECRET_KEY`, `JWT_EXPIRE_MINUTES=15`, `REFRESH_TOKEN_EXPIRE_DAYS=7`
- `RATE_LIMIT_DEFAULT=60/minute`, `RATE_LIMIT_AUTH=10/minute`, `RATE_LIMIT_VOICE=20/minute`

---

## STT / TTS (shared keys)

| Variable | Default | Used by |
|----------|---------|---------|
| `DEEPGRAM_API_KEY` | `""` | Questionnaire STT, ticketing live STT |
| `DEEPGRAM_STT_MODEL` | `nova-3` | |
| `DEEPGRAM_TTS_MODEL` | `aura-luna-en` | Questionnaire + ticketing fallback TTS |
| `ELEVENLABS_API_KEY` | `""` | Questionnaire clone TTS, ticketing stock TTS |
| `ELEVENLABS_VOICE_ID` | `""` | Questionnaire only (clone) |
| `ELEVENLABS_MODEL` | `eleven_multilingual_v2` | |

---

## Cabin settings (`CABIN_*`, `ELEVENLABS_STT_*`)

Unchanged — see `04-cabin.md` and `app/core/config.py` lines 74–127.

Notable: `CABIN_TEST_HARNESS`, `LLM_USD_TO_INR=88.0`.

---

## Ticketing-specific behaviour (constants in code, not env)

These are hardcoded in modules — not settings today:

| Constant | Value | Location |
|----------|-------|----------|
| `MAX_TRIAGE_TURNS` | 3 | `triage_engine.py` |
| `MIN_CONSULTATION_TURNS` | 7 | `consultation_engine.py` |
| `MAX_CONSULTATION_TURNS` | 12 | `consultation_engine.py` |
| `STALE_MINUTES` | 30 | `session_store.py` |
| `_UTTERANCE_END_MS` | 1000 | `deepgram_live.py` |
| `_SILENCE_TIMEOUT_SECS` | 20 | `voice_session.py` |
| `_MAX_SILENCE_RETRIES` | 2 | `voice_session.py` |

### Ticketing Voice V2 (env)

| Variable | Default | Role |
|----------|---------|------|
| `TICKETING_USE_GEMINI_LIVE` | `false` | Same WS URL; switches orchestrator |
| `GEMINI_LIVE_MODEL` | `gemini-2.5-flash-native-audio-preview-12-2025` | Live speech-to-speech model |
| `GEMINI_LIVE_VOICE` | `Puck` | Gemini prebuilt voice |
| `TICKETING_POST_CALL_MODEL` | empty → `ANTHROPIC_MODEL` | Post-call extract |
| `TICKETING_MAX_SESSION_MINUTES` | `15` | Hard cutoff then extract |
| `TICKETING_MAX_CONCURRENT_LIVE_SESSIONS_PER_HOSPITAL` | `5` | In-process cap at WS accept |
| `TICKETING_PERSIST_INTERVAL_SECS` | `15.0` | Transcript flush during call |

Ticket number format: `TKT-{seq:06d}`.

Default hospital language: `hi` (Hindi).

IST offset: UTC+5:30 — applied at API response boundary via `to_ist_str()`.

---

## Bootstrap

To enable one-time setup:

```env
ENABLE_SETUP_ENDPOINT=true
JWT_SECRET_KEY=<your-secret>
```

Then `POST /api/v2/setup` with body `secret` matching `JWT_SECRET_KEY`.

**Off by default** even when `DEBUG=true` — prevents accidental public bootstrap.
