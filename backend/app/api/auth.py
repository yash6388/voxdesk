from fastapi import APIRouter, HTTPException, Request, Response, status
from sqlalchemy import func, select, update

from app.api.deps import SessionDep
from app.auth import (
    CurrentUser,
    clear_session_cookie,
    create_token,
    hash_password,
    set_session_cookie,
    verify_password,
)
from app.db.models import Business, User
from app.ratelimit import LimiterDep, auth_limit, client_ip
from app.schemas import AuthResponse, LoginRequest, SignupRequest, UserOut

router = APIRouter(prefix="/auth", tags=["auth"])

# Verified against when the email doesn't exist, so a failed login takes the same time
# either way — response timing can't reveal which emails have accounts.
_DUMMY_HASH = hash_password("timing-equaliser-not-a-real-password")


def _authenticated(user: User, response: Response) -> AuthResponse:
    token = create_token(user.id)
    set_session_cookie(response, token)
    return AuthResponse(user=UserOut.model_validate(user), access_token=token)


@router.post("/signup", response_model=AuthResponse, status_code=status.HTTP_201_CREATED)
async def signup(
    body: SignupRequest,
    request: Request,
    response: Response,
    session: SessionDep,
    limiter: LimiterDep,
):
    await limiter.enforce(auth_limit(client_ip(request)))
    email = body.email.lower()
    if await session.scalar(select(User.id).where(User.email == email)):
        raise HTTPException(status.HTTP_409_CONFLICT, "An account with this email already exists")

    first_user = not await session.scalar(select(func.count()).select_from(User))
    user = User(email=email, name=body.name.strip(), password_hash=hash_password(body.password))
    session.add(user)
    await session.flush()
    if first_user:
        # Businesses created before accounts existed get an owner: the first person to sign up.
        await session.execute(
            update(Business).where(Business.owner_id.is_(None)).values(owner_id=user.id)
        )
    await session.commit()
    return _authenticated(user, response)


@router.post("/login", response_model=AuthResponse)
async def login(
    body: LoginRequest,
    request: Request,
    response: Response,
    session: SessionDep,
    limiter: LimiterDep,
):
    # Slows password guessing: a handful of attempts per minute per IP.
    await limiter.enforce(auth_limit(client_ip(request)))
    user = await session.scalar(select(User).where(User.email == body.email.lower()))
    if user is None:
        verify_password(body.password, _DUMMY_HASH)  # same cost as a real check
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid email or password")
    if not verify_password(body.password, user.password_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid email or password")
    return _authenticated(user, response)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(response: Response):
    clear_session_cookie(response)


@router.get("/me", response_model=UserOut)
async def me(user: CurrentUser):
    return user
