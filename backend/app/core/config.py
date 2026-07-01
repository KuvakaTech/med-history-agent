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
    ANTHROPIC_MODEL: str = "claude-sonnet-4-6"          # diagnosis, summary, completeness
    ANTHROPIC_FAST_MODEL: str = "claude-haiku-4-5-20251001"  # conversational turns
    # Groq — used for streaming when key is set (fastest inference)
    GROQ_API_KEY: str = ""
    GROQ_MODEL: str = "llama-3.3-70b-versatile"

    # STT / TTS
    DEEPGRAM_API_KEY: str = ""
    DEEPGRAM_STT_MODEL: str = "nova-3"
    DEEPGRAM_TTS_MODEL: str = "aura-luna-en"

    HOST: str = "0.0.0.0"
    PORT: int = 8001

    # Auth
    JWT_SECRET_KEY: str = ""                 # Secret used to sign JWTs (generate with: openssl rand -hex 32)
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRE_MINUTES: int = 15             # Short-lived access token (OAuth2 standard)
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7       # Long-lived refresh token stored in httpOnly cookie

    # Rate limiting — requests per minute (per IP, per uvicorn worker)
    RATE_LIMIT_DEFAULT: str = "60/minute"   # General API endpoints
    RATE_LIMIT_AUTH: str = "10/minute"      # Token endpoint — tight to prevent brute force
    RATE_LIMIT_VOICE: str = "20/minute"     # Audio / streaming endpoints

    @field_validator("BACKEND_CORS_ORIGINS", mode="before")
    @classmethod
    def parse_cors(cls, v: Union[str, list]) -> list:
        if isinstance(v, str) and not v.startswith("["):
            return [i.strip() for i in v.split(",") if i.strip()]
        if isinstance(v, (list, str)):
            return v
        raise ValueError(v)


settings = Settings()  # type: ignore[call-arg]
