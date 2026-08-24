# LLM & External Services

## LLM facade (`app/agent/llm.py`)

**Never call Anthropic/Groq/Gemini SDKs directly from services.**

| Function | Use case |
|----------|----------|
| `complete` | Plain text |
| `complete_structured` | Pydantic-validated output |
| `stream_complete` | Token stream (patient-visible text) |

### Fallback: Anthropic → Groq → Gemini

| Tier | Setting | Used for |
|------|---------|----------|
| `fast=True` | `ANTHROPIC_FAST_MODEL` (Haiku) | Conversational turns, cabin analysis, ticketing engines |
| `fast=False` | `ANTHROPIC_MODEL` (Sonnet) | Diagnosis, summary, completeness |

Structured: Anthropic forced tool-choice; `_extract_json` fallback.

Streaming: fallback only if zero tokens yielded.

### Usage telemetry (`app/agent/usage.py`)

- contextvars sink for cabin LLM cost
- `stream_complete` not instrumented
- Groq/Gemini priced at $0 in cost log

---

## Speech-to-text by product

| Product | Module | Provider | Notes |
|---------|--------|----------|-------|
| Questionnaire voice | `agent/transcription/service.py` | Deepgram nova-3 | `language=multi` for non-English |
| Cabin live | `cabin/scribe.py` | ElevenLabs Scribe v2 Realtime | Backend relays audio |
| Ticketing voice | `ticketing/deepgram_live.py` | Deepgram nova-3 WebSocket | UtteranceEnd after 1000ms silence. **V2:** Gemini Live native transcription when `TICKETING_USE_GEMINI_LIVE=true` (`ticketing/gemini_live.py`) |

### Ticketing Deepgram live (`DeepgramLiveStream`)

- PCM16 16kHz mono
- `interim_results=true` → partial transcripts to FE
- `utterance_end_ms=1000` → patient finished speaking
- Language: `multi` unless English; passed from session language
- Caller: `connect()`, `send_audio()`, `events()`, `keepalive()`, `close()`

---

## Text-to-speech by product

| Product | Module | Voice | Fallback |
|---------|--------|-------|------------|
| Questionnaire | `agent/tts/service.py` | ElevenLabs **cloned** voice if configured | Deepgram Aura |
| Ticketing | `ticketing/tts_service.py` | ElevenLabs **stock** Adam (`pNInz6obpgDQGcFmaJgB`) | Deepgram |
| v1 `/note/speak` | `agent/tts/service.py` | Same as questionnaire |

Ticketing TTS is **intentionally separate** from clinical TTS — stock multilingual voice, MP3 bytes returned as base64 in WS.

---

## Summarization (`app/agent/summarization/service.py`)

- SOAP note from transcript
- Used by: questionnaire pipeline, ticketing `_finalize()` in `voice_session.py`

---

## Cloudflare R2 (`app/storage/r2.py`)

- boto3 in executor
- Questionnaire + cabin audio archive
- Ticketing: no R2 usage currently
- Unconfigured → `/tmp` keys

---

## Service dependency map

```
questionnaire engine      → llm
pipeline services         → llm
cabin analysis/gaps       → llm + usage.record
ticketing triage_engine   → llm (complete_structured, stream_complete)
ticketing consultation    → llm
ticketing voice_session   → deepgram_live + tts_service + summarization + llm
questionnaire voice       → transcription (Deepgram) + r2 + agent/tts
cabin live                → scribe (ElevenLabs) + r2 + analysis
```

---

## Clinical services (questionnaire pipeline only)

| Module | Stage |
|--------|-------|
| `clinical/services/translation.py` | Translate |
| `clinical/services/completeness.py` | Completeness report |
| `agent/summarization/service.py` | SOAP |
| `clinical/services/diagnosis.py` | Differential |
| `clinical/services/prescription.py` | Rx (separate POST) |

Ticketing consultation engine explicitly does **not** call diagnosis, completeness, or prescription services.
