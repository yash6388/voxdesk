"""Owner authentication: Argon2 password hashing, JWT sessions, FastAPI dependencies.

The JWT travels in an httpOnly cookie (JavaScript can't read it, so an XSS bug can't steal
the session). An `Authorization: Bearer <token>` header is also accepted — handy for
Swagger and API clients.
"""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Annotated

import jwt
from fastapi import Depends, HTTPException, Request, Response, status
from pwdlib import PasswordHash
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import SessionDep
from app.config import get_settings
from app.db.models import Business, User

COOKIE_NAME = "voxdesk_session"
ALGORITHM = "HS256"

# Argon2id with the library's recommended parameters — memory-hard, so brute-forcing
# leaked hashes on GPUs is expensive.
_hasher = PasswordHash.recommended()


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    return _hasher.verify(password, password_hash)


def create_token(user_id: uuid.UUID) -> str:
    s = get_settings()
    now = datetime.now(UTC)
    payload = {
        "sub": str(user_id),
        "iat": now,
        "exp": now + timedelta(minutes=s.jwt_expire_minutes),
    }
    return jwt.encode(payload, s.jwt_secret, algorithm=ALGORITHM)


def set_session_cookie(response: Response, token: str) -> None:
    s = get_settings()
    response.set_cookie(
        COOKIE_NAME,
        token,
        max_age=s.jwt_expire_minutes * 60,
        httponly=True,
        secure=s.cookie_secure,
        samesite=s.cookie_samesite,
        path="/",
    )


def clear_session_cookie(response: Response) -> None:
    s = get_settings()
    response.delete_cookie(
        COOKIE_NAME, path="/", secure=s.cookie_secure, samesite=s.cookie_samesite
    )


def _token_from(request: Request) -> str | None:
    header = request.headers.get("authorization", "")
    if header.lower().startswith("bearer "):
        return header[7:].strip()
    return request.cookies.get(COOKIE_NAME)


_UNAUTHORIZED = HTTPException(
    status.HTTP_401_UNAUTHORIZED, "Not signed in", headers={"WWW-Authenticate": "Bearer"}
)


async def current_user(request: Request, session: SessionDep) -> User:
    token = _token_from(request)
    if not token:
        raise _UNAUTHORIZED
    try:
        # Verifies the signature AND the expiry ("exp") in one call.
        payload = jwt.decode(token, get_settings().jwt_secret, algorithms=[ALGORITHM])
        user_id = uuid.UUID(payload["sub"])
    except (jwt.PyJWTError, KeyError, ValueError):
        raise _UNAUTHORIZED from None
    user = await session.get(User, user_id)
    if user is None:
        raise _UNAUTHORIZED
    return user


CurrentUser = Annotated[User, Depends(current_user)]


async def get_owned_business(business_id: uuid.UUID, user: User, session: AsyncSession) -> Business:
    """404 — not 403 — when the business belongs to someone else, so other tenants
    can't even discover which business ids exist."""
    business = await session.get(Business, business_id)
    if business is None or business.owner_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Business not found")
    return business


async def owned_business(
    business_id: uuid.UUID, user: CurrentUser, session: SessionDep
) -> Business:
    return await get_owned_business(business_id, user, session)


OwnedBusiness = Annotated[Business, Depends(owned_business)]
