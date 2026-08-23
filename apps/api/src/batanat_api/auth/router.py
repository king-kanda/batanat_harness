"""Authentication endpoints.

Three: who am I, sign in, sign out.

Two details in `login` are deliberate and easy to get wrong.

**The failure message never says which half was wrong.** "No such user" and
"wrong password" are the same response, because the difference tells an attacker
which addresses are worth grinding.

**A missing user still costs a hash.** Returning early when the email is unknown
makes that case measurably faster, which is the same disclosure by a slower
route. So an unknown email is verified against a dummy hash and takes the same
~0.6s as a real one.

`/me` deliberately does *no* hashing. It is called on every page load, and
deriving "is this still the default password?" by running scrypt against the
default would put a 32MB, half-second KDF on the hottest endpoint in the app —
several browser tabs regaining focus at once would be enough to stall the API.
The answer is a stored flag instead, written when the password is set.
"""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, Request, Response, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select

from batanat_api.auth import sessions
from batanat_api.core.deps import SessionDep
from batanat_api.core.logging import get_logger
from batanat_api.db.models import User
from batanat_api.security.passwords import hash_password, needs_rehash, verify_password

log = get_logger(__name__)

router = APIRouter(prefix="/api/auth", tags=["auth"])

#: Verified against when the email is unknown, purely so the timing matches.
#: A real scrypt hash of a value nobody can supply.
DUMMY_HASH = hash_password("no-account-with-this-address")

GENERIC_FAILURE = "That email and password do not match an account."


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=200)


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


@router.post("/logout", status_code=204, summary="Sign out")
async def logout(request: Request, response: Response) -> Response:
    await sessions.destroy(request.cookies.get(sessions.COOKIE_NAME))
    response.delete_cookie(sessions.COOKIE_NAME, path="/")
    return Response(status_code=204)


def func_lower(column):
    """Case-insensitive email comparison. Addresses are not case-sensitive."""
    from sqlalchemy import func

    return func.lower(column)
