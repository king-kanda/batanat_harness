"""Authentication: password hashing, sessions, and the guards around login.

The two easiest things to get wrong in a login endpoint are both about
disclosure — telling an attacker which emails exist, either through the message
or through the timing. Both are tested here.
"""

from __future__ import annotations

import uuid

import pytest

from batanat_api.config import Settings, get_settings
from batanat_api.security.passwords import hash_password, needs_rehash, verify_password

# --- hashing -----------------------------------------------------------------


def test_a_password_round_trips() -> None:
    stored = hash_password("correct horse battery staple")
    assert verify_password("correct horse battery staple", stored) is True


def test_the_wrong_password_is_rejected() -> None:
    stored = hash_password("real-password")
    assert verify_password("Real-Password", stored) is False
    assert verify_password("real-password ", stored) is False
    assert verify_password("", stored) is False


def test_the_hash_does_not_contain_the_password() -> None:
    stored = hash_password("swordfish")
    assert "swordfish" not in stored


def test_each_hash_uses_a_fresh_salt() -> None:
    """Identical passwords must not produce identical hashes."""
    a, b = hash_password("same"), hash_password("same")
    assert a != b
    assert verify_password("same", a) and verify_password("same", b)


def test_the_stored_form_carries_its_parameters() -> None:
    """So the cost can be raised later without invalidating existing hashes."""
    stored = hash_password("x")
    prefix, n, r, p, salt, key = stored.split("$")
    assert prefix == "scrypt"
    assert (int(n), int(r), int(p)) == (2**15, 8, 1)


@pytest.mark.parametrize(
    "stored",
    [None, "", "not-a-hash", "scrypt$bad", "bcrypt$1$2$3$4$5", "scrypt$x$y$z$aa$bb"],
)
def test_a_malformed_stored_hash_never_authenticates(stored) -> None:
    assert verify_password("anything", stored) is False


def test_an_empty_password_cannot_be_hashed() -> None:
    with pytest.raises(ValueError):
        hash_password("")


def test_rehash_is_flagged_for_weaker_parameters() -> None:
    assert needs_rehash(None) is True
    assert needs_rehash("scrypt$1024$8$1$aa$bb") is True
    assert needs_rehash(hash_password("x")) is False


# --- the login endpoint's disclosure guards -----------------------------------


def test_unknown_email_and_wrong_password_give_the_same_message() -> None:
    """Different messages tell an attacker which addresses are worth grinding."""
    from batanat_api.auth.router import GENERIC_FAILURE

    assert "password" in GENERIC_FAILURE.lower()
    # One message, and it names neither which field was wrong nor the account.
    assert "no such" not in GENERIC_FAILURE.lower()
    assert "not found" not in GENERIC_FAILURE.lower()


def test_an_unknown_email_still_costs_a_full_hash() -> None:
    """Returning early for an unknown email leaks existence through timing.

    Asserted two ways: the fallback is in the code, and verifying against it
    costs the same order of magnitude as verifying a real hash — which is the
    property that actually matters.
    """
    import inspect
    import time

    from batanat_api.auth import router

    assert router.DUMMY_HASH.startswith("scrypt$")
    source = inspect.getsource(router.login)
    assert "user.password_hash if user else DUMMY_HASH" in source

    real = hash_password("a-real-password")

    start = time.perf_counter()
    verify_password("guess", real)
    real_seconds = time.perf_counter() - start

    start = time.perf_counter()
    verify_password("guess", router.DUMMY_HASH)
    dummy_seconds = time.perf_counter() - start

    # Same KDF and parameters, so the two must be within a small factor.
    assert 0.25 < (dummy_seconds / real_seconds) < 4.0, (
        f"unknown-email path took {dummy_seconds:.3f}s vs {real_seconds:.3f}s for a real one"
    )


# --- session cookie -----------------------------------------------------------


def test_the_session_cookie_is_locked_down() -> None:
    from batanat_api.auth.sessions import cookie_kwargs

    flags = cookie_kwargs()
    assert flags["httponly"] is True, "JavaScript must not be able to read the session"
    assert flags["samesite"] == "lax", "CSRF protection for cross-site requests"


def test_the_cookie_is_marked_secure_outside_localhost(monkeypatch: pytest.MonkeyPatch) -> None:
    from batanat_api.auth.sessions import cookie_kwargs

    monkeypatch.setattr(get_settings(), "api_public_url", "https://api.batanat.co.ke")
    assert cookie_kwargs()["secure"] is True

    monkeypatch.setattr(get_settings(), "api_public_url", "http://localhost:8000")
    assert cookie_kwargs()["secure"] is False


async def test_a_session_resolves_then_stops_after_logout() -> None:
    from batanat_api.auth import sessions

    user_id = uuid.uuid4()
    created = await sessions.create(user_id)

    assert await sessions.resolve(created.token) == user_id
    await sessions.destroy(created.token)
    assert await sessions.resolve(created.token) is None


async def test_an_unknown_token_resolves_to_nobody() -> None:
    from batanat_api.auth import sessions

    assert await sessions.resolve("not-a-real-token") is None
    assert await sessions.resolve(None) is None


async def test_session_tokens_are_unguessable() -> None:
    from batanat_api.auth import sessions

    tokens = {(await sessions.create(uuid.uuid4())).token for _ in range(20)}
    assert len(tokens) == 20
    assert all(len(t) >= 40 for t in tokens)


# --- the production guard -----------------------------------------------------


def test_local_tolerates_the_development_default() -> None:
    Settings(app_env="local", default_user_password="batanat-dev").assert_safe_for_environment()


@pytest.mark.parametrize("environment", ["staging", "production"])
def test_shipping_the_default_password_fails_the_boot(environment: str) -> None:
    """A default password that ships is not a default, it is a backdoor."""
    settings = Settings(
        app_env=environment,
        default_user_password="batanat-dev",
        session_secret="set",
        token_encryption_key="set",
    )
    with pytest.raises(RuntimeError, match="development default"):
        settings.assert_safe_for_environment()


def test_missing_secrets_also_fail_the_boot() -> None:
    settings = Settings(
        app_env="production",
        default_user_password="a-real-one",
        session_secret=None,
        token_encryption_key=None,
    )
    with pytest.raises(RuntimeError, match="SESSION_SECRET"):
        settings.assert_safe_for_environment()


def test_a_properly_configured_production_passes() -> None:
    Settings(
        app_env="production",
        default_user_password="a-real-one",
        session_secret="s",
        token_encryption_key="k",
    ).assert_safe_for_environment()
