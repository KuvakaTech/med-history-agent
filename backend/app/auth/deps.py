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
