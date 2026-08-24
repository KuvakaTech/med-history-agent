# Testing & Touch-points

## Test suite

Location: `backend/tests/` — `pytest`, `asyncio_mode=auto`.

Run from `backend/` with package installed: `pip install -e .` then `pytest`.

All tests offline — no MongoDB, no live LLM/STT/TTS.

### Approximate counts (~237 test functions)

| File | Tests | Domain |
|------|-------|--------|
| `test_ticketing_api.py` | 35 | v2 HTTP contracts, admin scoping |
| `test_ticketing_stores.py` | 30 | hospital/session/patient stores |
| `test_ticketing_models.py` | 13 | Pydantic models, IST helper |
| `test_ticketing_engines.py` | 14 | triage + consultation engines |
| `test_ticketing_voice_session.py` | 5 | voice session logic (no live WS) |
| `test_ticketing_gemini_live.py` | ~8 | Live config, VAD, tool parse (mocked) |
| `test_ticketing_voice_session_v2.py` | ~10 | barge-in, slots, finish_triage, ducking |
| `test_ticketing_post_call_extract.py` | ~4 | Claude extract + SOAP persist |
| `test_cabin_analysis.py` | 27 | cabin analysis |
| `test_cabin_live.py` | 28 | cabin orchestrator |
| `test_cabin_endpoints.py` | 13 | cabin HTTP/WS |
| `test_cabin_record_api.py` | 13 | record/override |
| `test_cabin_gaps.py` | 11 | gap alerts |
| `test_cabin_leases.py` | 11 | leases |
| `test_cabin_store_and_models.py` | 11 | cabin store |
| `test_cabin_postprocess.py` | 9 | rediarize |
| `test_cabin_audio_spool.py` | 7 | audio spool |
| `test_cabin_scribe.py` | 12 | scribe client (some may fail/hang live) |
| `test_llm_usage.py` | 10 | usage sink |
| `test_patient_profile.py` | 9 | clinical profile merge |

Ticketing tests patch stores to in-memory — Mongo never dialled.

---

## Lint / format

```bash
ruff check .
ruff format .
black .
```

Python: `>=3.11,<3.13`

Dev deps: Poetry group — use `poetry install` or install pytest/ruff/black directly.

---

## Project status (August 2026)

| Area | Status |
|------|--------|
| v1 questionnaire | Production path for doctor-led screener |
| v1 cabin | Phase 1 + 1.5 backend done; live ElevenLabs validation still blocking pilot |
| v2 ticketing | Backend + tests; public voice check-in flow |
| Ticketing frontend | Next.js routes referenced in setup (`/checkin/{slug}/start`, `/admin`) |
| Cabin Next.js UI | Outstanding (was Phase 1.5 item 5) |

---

## Where to touch code

| Task | Primary files |
|------|---------------|
| Questionnaire turns | `clinical/questionnaire/engine.py`, `consultation.py` helpers |
| Pipeline step | `clinical/services/*.py`, `consultation.py` `_pipeline_generator` |
| Cabin live | `cabin/live.py`, `cabin/analysis.py` |
| Ticketing voice flow | `ticketing/voice_session.py` (V1) or `ticketing/voice_session_v2.py` (Gemini Live) |
| Triage prompts/logic | `ticketing/triage_engine.py` |
| Consultation prompts | `ticketing/consultation_engine.py` |
| Ticketing WS events | `ticketing/events.py`, `voice_session.py` |
| Ticketing HTTP | `api/v2/endpoints/ticketing.py`, `ticketing_admin.py` |
| Hospital bootstrap | `api/v2/endpoints/setup.py`, `hospital_store.py` |
| New v2 endpoint | `api/v2/endpoints/`, register in `api/v2/api.py` |
| New Mongo index | `main.py` lifespan |
| Auth roles | `auth/deps.py`, `auth/user_store.py`, `auth/router.py` |
| LLM prompt (any) | Module next to the service — always via `agent/llm.py` |

---

## Key invariants to preserve

**Questionnaire:** MIN_TURNS=7, MAX_TURNS=10, one question/turn, LLM-judged `covered_areas`, three aligned transports.

**Cabin:** AI never speaks; partials never hit LLM; backend relays EL audio; lease fails open.

**Ticketing:** No barge-in (mic gated until `agent_done_speaking`); triage max 3 turns; consultation 7–12; phone globally unique; soft-delete only; stale active → partial; no diagnosis during flow; public WS has no JWT.
