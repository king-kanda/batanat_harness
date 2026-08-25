"""Authentication endpoints: who am I, sign in, sign out.

Three deliberate details, each easy to undo by accident:

- The login failure message never says which half was wrong; the difference
  tells an attacker which addresses are worth grinding.
- An unknown email still costs a hash, so it cannot be identified by timing.
- `/me` does no hashing at all. It runs on every page load, and deriving
  "still on the default password?" would put a 0.6s KDF on the hottest
  endpoint in the app. It reads a stored flag instead.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, Request, Response, status
from pydantic import BaseModel, EmailStr, Field, model_validator
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from batanat_api.auth import sessions
from batanat_api.core.deps import SessionDep
from batanat_api.core.logging import get_logger
from batanat_api.db.models import SkillVersion, User
from batanat_api.security.passwords import (
    hash_password,
    needs_rehash,
    set_password,
    verify_password,
)

log = get_logger(__name__)

router = APIRouter(prefix="/api/auth", tags=["auth"])

#: Verified against when the email is unknown, purely so the timing matches.
#: A real scrypt hash of a value nobody can supply.
DUMMY_HASH = hash_password("no-account-with-this-address")

GENERIC_FAILURE = "That email and password do not match an account."


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=200)


#: Short enough not to be a nuisance, long enough that scrypt is doing real work.
MIN_PASSWORD_LENGTH = 8


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=MIN_PASSWORD_LENGTH, max_length=200)
    confirm_password: str = Field(min_length=1, max_length=200)

    @model_validator(mode="after")
    def _passwords_match(self) -> RegisterRequest:
        if self.password != self.confirm_password:
            raise ValueError("The two passwords do not match.")
        return self


class CurrentUserView(BaseModel):
    id: str
    email: str
    name: str | None = None
    timezone: str
    #: True while the account still has the seeded development password.
    using_default_password: bool = False


def _client_address(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _view(user: User) -> CurrentUserView:
    return CurrentUserView(
        id=str(user.id),
        email=user.email,
        name=user.name,
        timezone=user.timezone,
        using_default_password=user.must_change_password,
    )


@router.get("/me", response_model=CurrentUserView, summary="The signed-in user")
async def me(request: Request, session: SessionDep) -> CurrentUserView:
    user_id = await sessions.resolve(request.cookies.get(sessions.COOKIE_NAME))
    if user_id is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not signed in.")

    user = (
        await session.execute(select(User).where(User.id == user_id, User.is_active.is_(True)))
    ).scalar_one_or_none()
    if user is None:
        # The session outlived the account.
        await sessions.destroy(request.cookies.get(sessions.COOKIE_NAME))
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not signed in.")

    return _view(user)


@router.post("/login", response_model=CurrentUserView, summary="Sign in")
async def login(
    body: LoginRequest, request: Request, response: Response, session: SessionDep
) -> CurrentUserView:
    address = _client_address(request)

    if await sessions.too_many_attempts(body.email, address):
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            "Too many sign-in attempts. Wait a few minutes and try again.",
        )

    user = (
        await session.execute(select(User).where(func_lower(User.email) == body.email.lower()))
    ).scalar_one_or_none()

    # Always hash, even with no user, so the two cases take the same time.
    stored = user.password_hash if user else DUMMY_HASH
    correct = verify_password(body.password, stored)

    if user is None or not correct or not user.is_active:
        log.warning("login.failed", address=address)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, GENERIC_FAILURE)

    # Upgrade the stored hash opportunistically if the cost has been raised.
    if needs_rehash(user.password_hash):
        user.password_hash = hash_password(body.password)

    user.last_login_at = datetime.now(UTC)
    await session.flush()

    await sessions.clear_attempts(body.email, address)
    created = await sessions.create(user.id)
    response.set_cookie(value=created.token, **sessions.cookie_kwargs())

    log.info("login.ok", user_id=str(user.id))
    return _view(user)


@router.post(
    "/register",
    response_model=CurrentUserView,
    status_code=status.HTTP_201_CREATED,
    summary="Create an account",
)
async def register(
    body: RegisterRequest, request: Request, response: Response, session: SessionDep
) -> CurrentUserView:
    """Create an account and sign it in.

    **Rate limited before anything is hashed.** Registration needs no session, and
    scrypt costs ~0.6s of CPU and 32MB by design, so hashing first would make this
    the cheapest way to exhaust the box.

    **The address is stored lowercased.** The unique index is on the raw column
    while `login` looks the address up case-insensitively, so storing what the
    user typed would let `Martin@x.com` and `martin@x.com` both exist — and then
    the login query matches two rows and `scalar_one_or_none` raises. Two
    accounts nobody can sign into.

    A new account also gets an active Skill.MD. Every trigger asks for the
    active version and passes its content to the model, so an account without
    one classifies against no criteria at all — an empty Rules page and a
    plausible-looking agent working from nothing.
    """
    from batanat_api.db.seed import DEFAULT_SKILL_MD

    if await sessions.too_many_registrations(_client_address(request)):
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            "Too many accounts created from here. Wait a few minutes and try again.",
        )

    email = body.email.lower()

    existing = (
        await session.execute(select(User).where(func_lower(User.email) == email))
    ).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "That email already has an account.")

    user = User(email=email, timezone="Africa/Nairobi")
    set_password(user, body.password)
    session.add(user)

    try:
        await session.flush()
    except IntegrityError:
        # Two registrations for the same address raced past the check above.
        # The unique index is the real guard; this turns it into the same 409.
        await session.rollback()
        raise HTTPException(
            status.HTTP_409_CONFLICT, "That email already has an account."
        ) from None

    session.add(
        SkillVersion(
            user_id=user.id,
            version=1,
            content=DEFAULT_SKILL_MD,
            checksum=hashlib.sha256(DEFAULT_SKILL_MD.encode()).hexdigest(),
            is_active=True,
            created_by="registration",
            notes="Starting criteria — edit these on the Rules page.",
        )
    )
    await session.flush()

    created = await sessions.create(user.id)
    response.set_cookie(value=created.token, **sessions.cookie_kwargs())

    log.info("register.ok", user_id=str(user.id))
    return _view(user)


@router.post("/logout", status_code=204, summary="Sign out")
async def logout(request: Request, response: Response) -> Response:
    await sessions.destroy(request.cookies.get(sessions.COOKIE_NAME))
    response.delete_cookie(sessions.COOKIE_NAME, path="/")
    return Response(status_code=204)


def func_lower(column):
    """Case-insensitive email comparison. Addresses are not case-sensitive."""
    from sqlalchemy import func

    return func.lower(column)
