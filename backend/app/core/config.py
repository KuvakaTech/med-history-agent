from __future__ import annotations

import os
from typing import List, Union

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=os.environ.get("ENV", ".env"),
        case_sensitive=True,
        extra="ignore",
    )

    PROJECT_NAME: str = "kuvaka Clinical AI"
    API_V1_STR: str = "/api/v1"
    VERSION: str = "1.0.0"
    DEBUG: bool = False

    BACKEND_CORS_ORIGINS: List[str] = []
    BACKEND_CORS_ALLOW_ALL: bool = False

    # MongoDB Atlas
    MONGODB_URI: str = "mongodb://localhost:27017"
    MONGODB_DB: str = "kuvaka"

    # Cloudflare R2 (S3-compatible)
    R2_ENDPOINT_URL: str = ""
    R2_ACCESS_KEY_ID: str = ""
    R2_SECRET_ACCESS_KEY: str = ""
    R2_BUCKET_NAME: str = "kuvaka-audio"

    # LLM
    GOOGLE_API_KEY: str = ""
    GEMINI_MODEL: str = "gemini-2.0-flash"
    GEMINI_FAST_MODEL: str = "gemini-2.0-flash"
    ANTHROPIC_API_KEY: str = ""
    ANTHROPIC_MODEL: str = "claude-sonnet-4-6"  # diagnosis, summary, completeness
    ANTHROPIC_FAST_MODEL: str = "claude-haiku-4-5-20251001"  # conversational turns
    # Groq — used for streaming when key is set (fastest inference)
    GROQ_API_KEY: str = ""
    GROQ_MODEL: str = "llama-3.3-70b-versatile"

    # STT / TTS
    DEEPGRAM_API_KEY: str = ""
    DEEPGRAM_STT_MODEL: str = "nova-3"
    DEEPGRAM_TTS_MODEL: str = "aura-luna-en"
    # ElevenLabs — cloned custom voice, speaks both English and Hindi.
    # When key + voice id are set it becomes the primary TTS; Deepgram is the fallback.
    ELEVENLABS_API_KEY: str = ""
    ELEVENLABS_VOICE_ID: str = ""
    ELEVENLABS_MODEL: str = "eleven_multilingual_v2"

    HOST: str = "0.0.0.0"
    PORT: int = 8001

    # Auth
    JWT_SECRET_KEY: str = (
        ""  # Secret used to sign JWTs (generate with: openssl rand -hex 32)
    )
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRE_MINUTES: int = 15  # Short-lived access token (OAuth2 standard)
    REFRESH_TOKEN_EXPIRE_DAYS: int = (
        7  # Long-lived refresh token stored in httpOnly cookie
    )

    # Rate limiting — requests per minute (per IP, per uvicorn worker)
    RATE_LIMIT_DEFAULT: str = "60/minute"  # General API endpoints
    RATE_LIMIT_AUTH: str = "10/minute"  # Token endpoint — tight to prevent brute force
    RATE_LIMIT_VOICE: str = "20/minute"  # Audio / streaming endpoints

    # ── Cabin consultation — live multi-speaker STT + analysis ──
    # Global host. The api.in.residency.* data-residency hosts reject this account's
    # key with auth_error — residency endpoints need a key issued in that region.
    ELEVENLABS_STT_WS_URL: str = "wss://api.elevenlabs.io/v1/speech-to-text/realtime"
    ELEVENLABS_STT_MODEL: str = "scribe_v2_realtime"
    ELEVENLABS_STT_BATCH_MODEL: str = "scribe_v2"  # post-consult diarizing pass
    CABIN_STT_SECONDARY_LANGUAGES: str = (
        "hin,eng,mar,guj"  # comma-separated ISO 639-3 codes; auto-detect among these
    )
    CABIN_STT_VAD_SILENCE_SECS: float = 0.7
    # Denoiser. Off because ElevenLabs rejects it combined with include_timestamps,
    # and word timings matter more than noise filtering for the clinical record.
    CABIN_STT_FILTER_BACKGROUND_AUDIO: bool = False
    CABIN_STT_NO_VERBATIM: bool = False  # per-clinic; default keeps the record verbatim
    CABIN_STT_ROLLING_RECONNECT_SECS: float = (
        1500.0  # cut over to a fresh EL socket before any undocumented session cap hits
    )
    CABIN_PANEL_MIN_INTERVAL_SECS: float = 8.0
    CABIN_ROLE_DEBOUNCE_SECS: float = 1.2
    CABIN_MIN_NEW_WORDS_FOR_ANALYSIS: int = 12
    # A full LiveSuggestions set is ~400 tokens. Under forced tool-use a truncated
    # response fails to parse, so the doctor gets NO suggestions rather than shorter
    # ones — leave real headroom rather than trimming this to save output tokens.
    CABIN_SUGGEST_MAX_TOKENS: int = 800
    CABIN_PANEL_MAX_TOKENS: int = 700  # a delta is small; caps a runaway response only
    CABIN_PANEL_RECONCILE_MAX_TOKENS: int = (
        2000  # a reconciliation returns the whole panel
    )
    # Deltas keep the screen responsive but cannot revise or drop an earlier entry, and
    # never revisit utterances they have already passed. A periodic full pass over the
    # whole transcript restores corrections, retractions, and anything a delta missed.
    CABIN_PANEL_RECONCILE_EVERY_N_PASSES: int = 12  # ~every 96s at the 8s panel cadence
    CABIN_SUGGEST_CONTEXT_UTTERANCES: int = 150  # covers a whole typical consult
    CABIN_PERSIST_INTERVAL_SECS: float = 15.0
    CABIN_AUDIO_QUEUE_MAX: int = 100
    CABIN_MAX_SESSION_MINUTES: int = 90
    CABIN_ARCHIVE_AUDIO: bool = True
    CABIN_REDIARIZE_ON_END: bool = True
    CABIN_TEST_HARNESS: bool = False  # dev-only /dev static mount
    # SlowAPIMiddleware does not cover WebSocket routes, so RATE_LIMIT_VOICE cannot
    # reach the cabin socket and stays deliberately unused. A concurrent-session cap is
    # the right shape here anyway: the cost is a held ElevenLabs socket, not requests.
    # Gap alerts (patient-history checks during the consult). Gaps move far more slowly
    # than the panel, so this runs on a longer cadence than the 8s panel pass and is
    # skipped entirely when the patient has no recorded history to check against.
    CABIN_GAP_MIN_INTERVAL_SECS: float = 120.0
    CABIN_GAP_MAX_TOKENS: int = 500
    CABIN_GAP_MAX_PASSES: int = 6  # hard per-session ceiling; bounds a runaway consult
    CABIN_MAX_CONCURRENT_SESSIONS_PER_DOCTOR: int = 3
    CABIN_LEASE_TTL_SECS: int = 120
    CABIN_LEASE_RENEW_SECS: float = 20.0  # TTL/6 — renewal shares the analysis loop

    # Only used for the per-session cost log line. A setting rather than a constant so
    # ops can correct it without a new image as the rate moves.
    LLM_USD_TO_INR: float = 88.0

    @field_validator("BACKEND_CORS_ORIGINS", mode="before")
    @classmethod
    def parse_cors(cls, v: Union[str, list]) -> list:
        if isinstance(v, str) and not v.startswith("["):
            return [i.strip() for i in v.split(",") if i.strip()]
        if isinstance(v, (list, str)):
            return v
        raise ValueError(v)


settings = Settings()  # type: ignore[call-arg]
