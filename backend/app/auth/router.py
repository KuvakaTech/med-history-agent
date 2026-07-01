"""Auth router — register, login, token refresh, logout."""
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Cookie, HTTPException, Request, Response, status
from jose import jwt
from pydantic import BaseModel, EmailStr, field_validator

from app.auth import refresh_store, user_store
from app.core.config import settings
from app.core.ratelimit import limiter

router = APIRouter()

_COOKIE = "refresh_token"
_COOKIE_PATH = "/api/v1/auth"


# ── Request / Response models ─────────────────────────────────────────────────

class RegisterRequest(BaseModel):
    name: str
    email: EmailStr
    password: str

    @field_validator("password")
    @classmethod
    def strong_enough(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError("Password must be at least 8 characters.")
        return v


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class UserInfo(BaseModel):
    id: str
    email: str
    name: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    user: UserInfo


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_access_token(user: dict) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user["_id"]),
        "email": user["email"],
        "name": user["name"],
        "iat": now,
        "exp": now + timedelta(minutes=settings.JWT_EXPIRE_MINUTES),
    }
    return jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def _token_response(user: dict) -> TokenResponse:
    return TokenResponse(
        access_token=_make_access_token(user),
        expires_in=settings.JWT_EXPIRE_MINUTES * 60,
        user=UserInfo(id=str(user["_id"]), email=user["email"], name=user["name"]),
    )


def _set_refresh_cookie(response: Response, raw_token: str) -> None:
    response.set_cookie(
        key=_COOKIE,
        value=raw_token,
        httponly=True,
        secure=not settings.DEBUG,
        samesite="lax",
        max_age=settings.REFRESH_TOKEN_EXPIRE_DAYS * 86400,
        path=_COOKIE_PATH,
    )


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
@limiter.limit(settings.RATE_LIMIT_AUTH)
async def register(request: Request, body: RegisterRequest, response: Response) -> TokenResponse:
    """Create a new doctor account and return tokens."""
    hashed = user_store.hash_password(body.password)
    try:
        user = await user_store.create(body.email, body.name, hashed)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))

    raw_refresh = refresh_store.generate()
    await refresh_store.store(raw_refresh, settings.REFRESH_TOKEN_EXPIRE_DAYS, user_id=str(user["_id"]))
    _set_refresh_cookie(response, raw_refresh)
    return _token_response(user)


@router.post("/login", response_model=TokenResponse)
@limiter.limit(settings.RATE_LIMIT_AUTH)
async def login(request: Request, body: LoginRequest, response: Response) -> TokenResponse:
    """Authenticate with email + password and return tokens."""
    user = await user_store.get_by_email(body.email)
    if not user or not user_store.verify_password(body.password, user["hashed_password"]):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password.",
        )

    raw_refresh = refresh_store.generate()
    await refresh_store.store(raw_refresh, settings.REFRESH_TOKEN_EXPIRE_DAYS, user_id=str(user["_id"]))
    _set_refresh_cookie(response, raw_refresh)
    return _token_response(user)


@router.post("/refresh", response_model=TokenResponse)
async def refresh(
    response: Response,
    refresh_token: Optional[str] = Cookie(default=None, alias=_COOKIE),
) -> TokenResponse:
    """Rotate the refresh token and issue a new access token."""
    if not refresh_token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="No refresh token.")

    new_raw = refresh_store.generate()
    user_id = await refresh_store.rotate(refresh_token, new_raw, settings.REFRESH_TOKEN_EXPIRE_DAYS)

    if not user_id:
        response.delete_cookie(_COOKIE, path=_COOKIE_PATH)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token expired or already used.",
        )

    user = await user_store.get_by_id(user_id)
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found.")

    _set_refresh_cookie(response, new_raw)
    return _token_response(user)


@router.post("/logout")
async def logout(
    response: Response,
    refresh_token: Optional[str] = Cookie(default=None, alias=_COOKIE),
) -> dict:
    """Revoke the refresh token and clear the cookie."""
    if refresh_token:
        await refresh_store.revoke(refresh_token)
    response.delete_cookie(_COOKIE, path=_COOKIE_PATH)
    return {"ok": True}
