"""Auth dependencies — reusable FastAPI Depends() for HTTP and WebSocket routes."""
from fastapi import Depends, HTTPException, Query, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt

from app.core.config import settings

_bearer = HTTPBearer(auto_error=True)


def _decode(token: str) -> dict:
    if not settings.JWT_SECRET_KEY:
        raise HTTPException(status_code=500, detail="JWT_SECRET_KEY not configured.")
    try:
        return jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token.",
            headers={"WWW-Authenticate": "Bearer"},
        )


async def verify_token(
    credentials: HTTPAuthorizationCredentials = Depends(_bearer),
) -> dict:
    """HTTP dependency — validates Bearer JWT in Authorization header."""
    return _decode(credentials.credentials)


async def verify_ws_token(token: str = Query(..., description="JWT access token")) -> dict:
    """WebSocket dependency — validates JWT passed as ?token= query param."""
    return _decode(token)


async def require_hospital_admin(
    credentials: HTTPAuthorizationCredentials = Depends(_bearer),
) -> dict:
    """Requires role == hospital_admin OR super_admin.

    super_admin is granted access to all hospitals. hospital_admin is scoped
    to the hospital_id stored in their JWT claim.
    """
    payload = _decode(credentials.credentials)
    role = payload.get("role", "doctor")
    if role not in ("hospital_admin", "super_admin"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Hospital admin access required.",
        )
    return payload


async def require_super_admin(
    credentials: HTTPAuthorizationCredentials = Depends(_bearer),
) -> dict:
    """Requires role == super_admin."""
    payload = _decode(credentials.credentials)
    if payload.get("role") != "super_admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Super admin access required.",
        )
    return payload
