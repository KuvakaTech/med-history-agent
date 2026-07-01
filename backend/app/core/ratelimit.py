"""Central rate limiter — all limits come from settings, never hardcoded here."""
from fastapi import Request
from slowapi import Limiter

from app.core.config import settings


def _get_real_ip(request: Request) -> str:
    """Respect Cloudflare's CF-Connecting-IP so limits are per real client, not proxy IP."""
    return (
        request.headers.get("CF-Connecting-IP")
        or (request.headers.get("X-Forwarded-For") or "").split(",")[0].strip()
        or (request.client.host if request.client else "unknown")
    )


limiter = Limiter(
    key_func=_get_real_ip,
    default_limits=[settings.RATE_LIMIT_DEFAULT],
)
