"""Creating an account.

Two things here are load-bearing beyond the obvious happy path.

**The address is stored lowercased.** The unique index is on the raw column,
while `login` looks the address up case-insensitively. Store what the user
typed and `Martin@x.com` and `martin@x.com` both insert cleanly — after which
the login query matches two rows, `scalar_one_or_none` raises, and neither
account can ever be signed into.

**A new account gets an active Skill.MD.** Every trigger reads the active
version and hands its content to the model. Without one the agent classifies
against no criteria at all, which does not fail loudly: it produces confident
verdicts from nothing and an empty Rules page.
"""

from __future__ import annotations

import uuid

import pytest
from fastapi import HTTPException, Request, Response
from pydantic import ValidationError
from sqlalchemy import func, select

from batanat_api.auth import sessions
from batanat_api.auth.router import RegisterRequest, register
from batanat_api.db.models import SkillVersion, User
from batanat_api.security.passwords import verify_password


def _address() -> str:
    return f"new-{uuid.uuid4().hex[:8]}@batanat.co.ke"


def _request(client_ip: str | None = None) -> Request:
    """A minimal ASGI scope — `register` only reads headers and the client host.

    Each test gets its own address by default, because the rate limiter counts
    per address in Redis and Redis outlives a single test.
    """
    host = client_ip or f"198.51.100.{uuid.uuid4().int % 200 + 1}"
    return Request({"type": "http", "headers": [], "client": (host, 0)})


async def _register(session, email: str, password: str = "a-good-password", request=None):
    body = RegisterRequest(email=email, password=password, confirm_password=password)
    return await register(body, request or _request(), Response(), session)


# --- the request model -------------------------------------------------------


def test_mismatched_passwords_are_rejected() -> None:
    with pytest.raises(ValidationError, match="do not match"):
        RegisterRequest(
            email="someone@batanat.co.ke", password="a-good-password", confirm_password="different"
        )


@pytest.mark.parametrize("password", ["", "short", "sevench"])
def test_a_password_under_the_minimum_is_rejected(password: str) -> None:
    with pytest.raises(ValidationError):
        RegisterRequest(email="someone@batanat.co.ke", password=password, confirm_password=password)


def test_a_password_at_the_minimum_is_accepted() -> None:
    body = RegisterRequest(
        email="someone@batanat.co.ke", password="eightchr", confirm_password="eightchr"
    )
    assert body.password == "eightchr"


# --- creating the account ----------------------------------------------------


async def test_registering_creates_a_usable_account(session) -> None:
    email = _address()
    view = await _register(session, email, "a-good-password")

    assert view.email == email
    # Not the seeded-default state: this is a real password the user chose.
    assert view.using_default_password is False

    user = (await session.execute(select(User).where(User.id == uuid.UUID(view.id)))).scalar_one()
    assert user.is_active is True
    assert verify_password("a-good-password", user.password_hash)


async def test_the_password_is_not_stored_in_the_clear(session) -> None:
    user_id = uuid.UUID((await _register(session, _address(), "a-good-password")).id)

    user = (await session.execute(select(User).where(User.id == user_id))).scalar_one()
    assert "a-good-password" not in (user.password_hash or "")


async def test_registering_signs_the_account_in(session) -> None:
    """The cookie is set on the response, so there is no second sign-in step."""
    body = RegisterRequest(
        email=_address(), password="a-good-password", confirm_password="a-good-password"
    )
    response = Response()
    await register(body, _request(), response, session)

    assert "batanat_session" in response.headers.get("set-cookie", "")


async def test_a_new_account_gets_an_active_skill(session) -> None:
    user_id = uuid.UUID((await _register(session, _address())).id)

    skills = (
        (await session.execute(select(SkillVersion).where(SkillVersion.user_id == user_id)))
        .scalars()
        .all()
    )
    assert len(skills) == 1
    assert skills[0].is_active is True
    assert skills[0].version == 1
    assert skills[0].content.strip(), "an active skill with no content is the same as none"


# --- addresses ---------------------------------------------------------------


async def test_the_address_is_stored_lowercased(session) -> None:
    local = f"Mixed-{uuid.uuid4().hex[:8]}"
    view = await _register(session, f"{local}@Batanat.CO.KE")

    assert view.email == f"{local}@batanat.co.ke".lower()


async def test_a_duplicate_address_is_refused(session) -> None:
    email = _address()
    await _register(session, email)

    with pytest.raises(HTTPException) as caught:
        await _register(session, email)
    assert caught.value.status_code == 409


async def test_a_duplicate_differing_only_in_case_is_refused(session) -> None:
    """The case that would otherwise produce two accounts nobody can sign into."""
    email = _address()
    await _register(session, email)

    with pytest.raises(HTTPException) as caught:
        await _register(session, email.upper())
    assert caught.value.status_code == 409

    count = (
        await session.execute(
            select(func.count(User.id)).where(func.lower(User.email) == email.lower())
        )
    ).scalar_one()
    assert count == 1


# --- rate limiting -----------------------------------------------------------


async def test_registration_is_rate_limited_per_address(session) -> None:
    """The limit must bite before scrypt runs, or this endpoint is a CPU sink.

    Registration needs no session and hashes a password on every call, which is
    ~0.6s of CPU by design. Without a limit in front of it, a loop against a
    small box is a denial of service that costs the attacker nothing.
    """
    caller = _request("203.0.113.77")

    for _ in range(sessions.MAX_REGISTRATIONS_PER_ADDRESS):
        await _register(session, _address(), request=caller)

    with pytest.raises(HTTPException) as caught:
        await _register(session, _address(), request=caller)
    assert caught.value.status_code == 429


async def test_the_registration_limit_is_separate_from_the_login_limit(session) -> None:
    """Sharing one counter would let each attack suppress the other's victim."""
    address = "203.0.113.78"

    for _ in range(sessions.MAX_ATTEMPTS_PER_ADDRESS + 1):
        await sessions.too_many_attempts("grinding@batanat.co.ke", address)

    # Failed logins from this address must not stop someone signing up.
    view = await _register(session, _address(), request=_request(address))
    assert view.id
