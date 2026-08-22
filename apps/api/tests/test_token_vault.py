"""The token vault: envelope encryption, refresh behaviour, and secret hygiene.

The acceptance criterion for phase 1 is that a token round-trips and that a
plaintext token never appears in a log line. Both are asserted here, the second
by capturing everything the vault logs during a full refresh cycle and
searching it for the secrets.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from cryptography.fernet import Fernet
from sqlalchemy.exc import IntegrityError

from batanat_api.core.logging import configure_logging
from batanat_api.db import enums
from batanat_api.db.models import Connection
from batanat_api.security import crypto, token_vault
from batanat_api.security.crypto import (
    EncryptionError,
    MasterKeyMissingError,
    SealedSecret,
    open_sealed,
    seal,
)
from batanat_api.security.token_vault import (
    ReauthorizationRequiredError,
    TokenSet,
    apply_token_set,
    get_valid_access_token,
    needs_refresh,
    read_access_token,
    read_refresh_token,
    register_refresher,
)

SECRET = "1//0gRefreshTokenThatMustNeverLeak"
ACCESS = "ya29.AccessTokenThatMustNeverLeak"


# --- encryption --------------------------------------------------------------


def test_secret_round_trips() -> None:
    sealed = seal(SECRET)
    assert open_sealed(sealed) == SECRET


def test_ciphertext_does_not_contain_the_plaintext() -> None:
    sealed = seal(SECRET)
    assert SECRET.encode() not in sealed.ciphertext
    assert SECRET.encode() not in sealed.wrapped_key


def test_each_seal_uses_a_fresh_data_key() -> None:
    """Two seals of the same value must not produce the same ciphertext."""
    a, b = seal(SECRET), seal(SECRET)
    assert a.ciphertext != b.ciphertext
    assert a.wrapped_key != b.wrapped_key
    assert open_sealed(a) == open_sealed(b) == SECRET


def test_repr_never_leaks_the_bytes() -> None:
    sealed = seal(SECRET)
    assert "redacted" in repr(sealed)
    assert str(sealed.ciphertext) not in repr(sealed)


def test_tampered_ciphertext_is_rejected_not_silently_wrong() -> None:
    sealed = seal(SECRET)
    tampered = SealedSecret(
        ciphertext=sealed.ciphertext[:-4] + b"AAAA", wrapped_key=sealed.wrapped_key
    )
    with pytest.raises(EncryptionError):
        open_sealed(tampered)


def test_wrong_master_key_cannot_open(monkeypatch: pytest.MonkeyPatch) -> None:
    sealed = seal(SECRET)
    from batanat_api.config import get_settings

    monkeypatch.setattr(get_settings(), "token_encryption_key", Fernet.generate_key().decode())
    with pytest.raises(EncryptionError, match="master key"):
        open_sealed(sealed)


def test_missing_master_key_fails_loudly(monkeypatch: pytest.MonkeyPatch) -> None:
    from batanat_api.config import get_settings

    monkeypatch.setattr(get_settings(), "token_encryption_key", None)
    with pytest.raises(MasterKeyMissingError):
        seal(SECRET)


def test_rotation_rewraps_the_key_without_touching_the_ciphertext(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The point of the envelope: rotating the master key is cheap."""
    from batanat_api.config import get_settings

    old_key = get_settings().token_encryption_key
    sealed = seal(SECRET)

    new_key = Fernet.generate_key().decode()
    monkeypatch.setattr(get_settings(), "token_encryption_key", new_key)

    rewrapped = crypto.rewrap(sealed, old_master_key=old_key)

    assert rewrapped.ciphertext == sealed.ciphertext  # untouched
    assert rewrapped.wrapped_key != sealed.wrapped_key
    assert open_sealed(rewrapped) == SECRET


# --- vault behaviour ---------------------------------------------------------


def _connection(**kwargs) -> Connection:
    defaults = dict(
        id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        provider=enums.Provider.zoho,
        external_account="org-123",
        scopes=[],
        status=enums.ConnectionStatus.connected,
    )
    return Connection(**{**defaults, **kwargs})


def test_apply_token_set_stores_both_tokens_encrypted() -> None:
    conn = _connection()
    apply_token_set(
        conn,
        TokenSet(
            access_token=ACCESS,
            refresh_token=SECRET,
            expires_in=3600,
            api_domain="https://www.zohoapis.eu",
            accounts_url="https://accounts.zoho.eu",
        ),
    )

    assert conn.access_token_ciphertext is not None
    assert ACCESS.encode() not in conn.access_token_ciphertext
    assert SECRET.encode() not in conn.refresh_token_ciphertext

    assert read_access_token(conn) == ACCESS
    assert read_refresh_token(conn) == SECRET
    # The DC-specific endpoints are persisted, never assumed.
    assert conn.api_domain == "https://www.zohoapis.eu"
    assert conn.accounts_url == "https://accounts.zoho.eu"


def test_refresh_token_is_kept_when_a_provider_omits_it() -> None:
    """Google returns no refresh_token on refresh; losing it would be fatal."""
    conn = _connection()
    apply_token_set(conn, TokenSet(access_token=ACCESS, refresh_token=SECRET, expires_in=3600))
    apply_token_set(conn, TokenSet(access_token="new-access", refresh_token=None, expires_in=3600))

    assert read_refresh_token(conn) == SECRET
    assert read_access_token(conn) == "new-access"


@pytest.mark.parametrize(
    ("expires_in_seconds", "expected"),
    [
        (3600, False),  # comfortably valid
        (120, True),  # inside the 5-minute margin
        (-10, True),  # already expired
    ],
)
def test_needs_refresh_respects_the_margin(expires_in_seconds: int, expected: bool) -> None:
    now = datetime.now(UTC)
    conn = _connection()
    apply_token_set(conn, TokenSet(access_token=ACCESS, refresh_token=SECRET, expires_in=3600))
    conn.access_expires_at = now + timedelta(seconds=expires_in_seconds)
    assert needs_refresh(conn, now=now) is expected


def test_a_connection_with_no_access_token_needs_refresh() -> None:
    assert needs_refresh(_connection()) is True


def test_no_advertised_expiry_is_treated_as_long_lived() -> None:
    conn = _connection()
    apply_token_set(conn, TokenSet(access_token=ACCESS, refresh_token=SECRET, expires_in=None))
    assert needs_refresh(conn) is False


# --- the full refresh path, against a real database --------------------------


class _FakeRefresher:
    def __init__(self, tokens: TokenSet | None = None, raises: Exception | None = None):
        self.tokens = tokens
        self.raises = raises
        self.calls = 0

    async def refresh(self, connection: Connection, refresh_token: str) -> TokenSet:
        self.calls += 1
        self.seen_refresh_token = refresh_token
        if self.raises:
            raise self.raises
        assert self.tokens
        return self.tokens


@pytest.fixture
def _restore_refreshers():
    original = dict(token_vault._REFRESHERS)
    yield
    token_vault._REFRESHERS.clear()
    token_vault._REFRESHERS.update(original)


async def test_expired_token_is_refreshed_and_persisted(session, user, _restore_refreshers) -> None:
    conn = _connection(user_id=user.id, provider=enums.Provider.zoho)
    apply_token_set(conn, TokenSet(access_token="stale", refresh_token=SECRET, expires_in=3600))
    conn.access_expires_at = datetime.now(UTC) - timedelta(minutes=1)
    session.add(conn)
    await session.commit()

    refresher = _FakeRefresher(TokenSet(access_token="fresh-token", expires_in=3600))
    register_refresher(enums.Provider.zoho, refresher)

    token = await get_valid_access_token(session, user.id, enums.Provider.zoho)
    await session.commit()

    assert token == "fresh-token"
    assert refresher.calls == 1
    assert refresher.seen_refresh_token == SECRET

    await session.refresh(conn)
    assert read_access_token(conn) == "fresh-token"
    assert conn.status is enums.ConnectionStatus.connected


async def test_valid_token_is_returned_without_calling_the_provider(
    session, user, _restore_refreshers
) -> None:
    conn = _connection(user_id=user.id, provider=enums.Provider.gmail)
    apply_token_set(conn, TokenSet(access_token=ACCESS, refresh_token=SECRET, expires_in=3600))
    session.add(conn)
    await session.commit()

    refresher = _FakeRefresher(TokenSet(access_token="should-not-be-used"))
    register_refresher(enums.Provider.gmail, refresher)

    assert await get_valid_access_token(session, user.id, enums.Provider.gmail) == ACCESS
    assert refresher.calls == 0


async def test_rejected_refresh_marks_the_connection_expired(
    session, user, _restore_refreshers
) -> None:
    """The weekly Gmail testing-mode failure. The UI reads this status."""
    conn = _connection(user_id=user.id, provider=enums.Provider.gmail)
    apply_token_set(conn, TokenSet(access_token="stale", refresh_token=SECRET, expires_in=-1))
    session.add(conn)
    await session.commit()

    register_refresher(
        enums.Provider.gmail,
        _FakeRefresher(raises=ReauthorizationRequiredError("invalid_grant")),
    )

    with pytest.raises(ReauthorizationRequiredError):
        await get_valid_access_token(session, user.id, enums.Provider.gmail)

    await session.refresh(conn)
    assert conn.status is enums.ConnectionStatus.expired


async def test_connection_without_a_refresh_token_demands_reauthorization(
    session, user, _restore_refreshers
) -> None:
    conn = _connection(user_id=user.id, provider=enums.Provider.zoho)
    session.add(conn)
    await session.commit()

    with pytest.raises(ReauthorizationRequiredError):
        await get_valid_access_token(session, user.id, enums.Provider.zoho)


# --- the acceptance criterion ------------------------------------------------


async def test_no_plaintext_token_ever_reaches_a_log_line(
    session, user, capsys, _restore_refreshers
) -> None:
    """Drive a full refresh cycle and search every emitted log line for secrets."""
    configure_logging("debug")

    conn = _connection(user_id=user.id, provider=enums.Provider.zoho)
    apply_token_set(conn, TokenSet(access_token=ACCESS, refresh_token=SECRET, expires_in=-1))
    session.add(conn)
    await session.commit()
    capsys.readouterr()

    new_access = "ya29.BrandNewAccessToken"
    new_refresh = "1//0gBrandNewRefreshToken"
    register_refresher(
        enums.Provider.zoho,
        _FakeRefresher(
            TokenSet(access_token=new_access, refresh_token=new_refresh, expires_in=3600)
        ),
    )

    await get_valid_access_token(session, user.id, enums.Provider.zoho)
    await session.commit()

    output = capsys.readouterr().out
    assert output.strip(), "expected the vault to log the refresh"

    for secret in (SECRET, ACCESS, new_access, new_refresh):
        assert secret not in output, f"{secret[:12]}… leaked into the logs"

    # And every line really was structured JSON, not a stray print.
    for line in output.strip().splitlines():
        json.loads(line)


async def test_explicitly_logging_a_token_is_still_redacted(capsys) -> None:
    """Belt and braces: even a careless call site cannot leak."""
    from batanat_api.core.logging import get_logger

    configure_logging("debug")
    get_logger("careless").info("oops", access_token=ACCESS, nested={"refresh_token": SECRET})

    output = capsys.readouterr().out
    assert ACCESS not in output
    assert SECRET not in output


# --- schema-level guarantees -------------------------------------------------


async def test_one_connection_per_user_provider_account(session, user) -> None:
    for _ in range(2):
        session.add(
            _connection(
                user_id=user.id, provider=enums.Provider.gmail, external_account="a@example.com"
            )
        )
    with pytest.raises(IntegrityError):
        await session.commit()
