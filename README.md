# Clinical AI — Pre-Consultation History Taking Assistant

An AI-powered clinical screener that conducts a brief patient history interview before the physician consultation. Handles voice and text input, streams responses in real time, detects clinical red flags, and generates a structured SOAP note with differential diagnoses.

> **Disclaimer:** This software is intended as a physician-support tool only. It does not replace professional medical judgment, diagnosis, or treatment. All outputs must be reviewed by a licensed clinician before acting on them.

---

## Features

- **Voice & text input** — patients answer by speaking or typing
- **Streaming AI responses** — questions appear token-by-token with sentence-level TTS playback
- **Red flag detection** — critical and important clinical flags surface in real time
- **Tiered LLM pipeline** — fast model (Haiku) for conversational turns, capable model (Sonnet/Gemini) for diagnosis and summary
- **Pre-screening scope** — 5–6 targeted questions, junior-doctor framing ("open the door, let the MD take it from there")
- **SOAP note generation** — structured note, differential diagnoses, suggested workup, and prescription support
- **Voice pipeline** — audio streamed chunk-by-chunk to the server; R2 upload and STT run in parallel post-recording
- **Multi-specialty** — General Medicine, Psychotherapy, Gynecology

---

## Architecture

```
frontend/          Next.js 14 (App Router) — patient-facing UI
backend/           FastAPI — clinical engine, LLM, STT, TTS, MongoDB
notetaker/         Standalone Gradio prototype (legacy / research)
docker-compose.yml Orchestrates MongoDB + backend + frontend
```

**Key integrations:**
| Service | Purpose |
|---------|---------|
| Anthropic Claude | Conversational history taking (Haiku) + diagnosis/summary (Sonnet) |
| Google Gemini | Alternative LLM provider (Gemini Flash) |
| Deepgram | Speech-to-text (Nova 3) + text-to-speech (Luna) |
| MongoDB Atlas | Session and consultation storage |
| Cloudflare R2 | Audio recording storage (S3-compatible) |

---

## Prerequisites

- Python 3.12+
- Node.js 20+
- MongoDB (local or Atlas)
- API keys: [Anthropic](https://console.anthropic.com), [Deepgram](https://console.deepgram.com), and optionally [Google AI](https://aistudio.google.com)
- (Optional) Cloudflare R2 bucket for audio storage

---

## Quick Start

### 1. Clone and configure

```bash
git clone https://github.com/your-org/clinical-ai.git
cd clinical-ai

# Backend
cp backend/.env.example backend/.env
# Edit backend/.env — fill in your API keys

# Frontend
cp frontend/.env.local.example frontend/.env.local
# Edit frontend/.env.local if needed (default points to localhost:8001)
```

### 2. Run with Docker (recommended)

```bash
docker compose up --build
```

Open [http://localhost:3000](http://localhost:3000).

### 3. Run locally (development)

**Backend:**
```bash
cd backend
python -m venv .venv
source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -e .
uvicorn app.main:app --reload --port 8001
```

**Frontend:**
```bash
cd frontend
npm install
npm run dev
```

Open [http://localhost:3000](http://localhost:3000).

---

## Environment Variables

### Backend (`backend/.env`)

| Variable | Required | Description |
|----------|----------|-------------|
| `MONGODB_URI` | Yes | MongoDB connection string |
| `MONGODB_DB` | Yes | Database name (default: `kuvaka`) |
| `ANTHROPIC_API_KEY` | Yes* | Anthropic API key |
| `ANTHROPIC_MODEL` | No | Sonnet model for diagnosis (default: `claude-sonnet-4-6`) |
| `ANTHROPIC_FAST_MODEL` | No | Haiku model for Q&A turns (default: `claude-haiku-4-5-20251001`) |
| `GOOGLE_API_KEY` | Yes* | Google AI API key |
| `GEMINI_MODEL` | No | Gemini model (default: `gemini-2.0-flash`) |
| `DEEPGRAM_API_KEY` | Yes | Deepgram API key |
| `DEEPGRAM_STT_MODEL` | No | STT model (default: `nova-3`) |
| `DEEPGRAM_TTS_MODEL` | No | TTS voice (default: `aura-luna-en`) |
| `R2_ENDPOINT_URL` | No | Cloudflare R2 endpoint URL |
| `R2_ACCESS_KEY_ID` | No | R2 access key |
| `R2_SECRET_ACCESS_KEY` | No | R2 secret key |
| `R2_BUCKET_NAME` | No | R2 bucket name |

*At least one LLM provider (Anthropic or Google) is required.

### Frontend (`frontend/.env.local`)

| Variable | Required | Description |
|----------|----------|-------------|
| `NEXT_PUBLIC_API_BASE_URL` | No | Backend URL (default: `http://localhost:8001`) |

---

## API Overview

```
POST /api/v1/consultation/start              Start a new session
POST /api/v1/consultation/{id}/answer        Submit a text answer (sync)
POST /api/v1/consultation/{id}/answer-stream Submit a text answer (SSE streaming)
WS   /api/v1/consultation/{id}/voice-stream  Stream voice audio (WebSocket)
GET  /api/v1/consultation/{id}/qa-log        Fetch Q&A history
POST /api/v1/consultation/{id}/pipeline      Run diagnosis pipeline (SSE)
POST /api/v1/consultation/{id}/prescribe     Generate prescription
GET  /health                                 Health check
```

---

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md).

## Security

See [SECURITY.md](SECURITY.md) for how to report vulnerabilities.

## License

MIT — see [LICENSE](LICENSE).
