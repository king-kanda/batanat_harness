"""The token vault.

The only code in the system that touches OAuth credentials. Everything else
asks for a usable access token and gets a string; nothing else reads, writes or
decrypts the `connections` token columns.

`get_valid_access_token()` refreshes transparently: if the stored access token
is missing or within the refresh margin of expiry, it exchanges the refresh
token, persists the new pair, and returns the fresh token. Callers never think
about expiry.

Provider-specific refresh is delegated to a registered `TokenRefresher`. Phase 1
ships the vault and the protocol; phase 2 registers the Google and Zoho
implementations. An unregistered provider raises rather than silently returning
a stale token.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Protocol

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from batanat_api.core.logging import get_logger
from batanat_api.db import enums
from batanat_api.db.models import Connection
from batanat_api.security.crypto import SealedSecret, open_sealed, seal

log = get_logger(__name__)

# Refresh this far ahead of expiry, so a token cannot die mid-request.
REFRESH_MARGIN = timedelta(minutes=5)


class TokenSet(BaseModel):
    """What a provider hands back from a token exchange."""

    access_token: str
    refresh_token: str | None = None
    expires_in: int | None = Field(default=None, description="Seconds until the access token dies.")
    scopes: list[str] = Field(default_factory=list)
    api_domain: str | None = None
    accounts_url: str | None = None

    def expires_at(self, *, now: datetime | None = None) -> datetime | None:
        if self.expires_in is None:
            return None
        return (now or datetime.now(UTC)) + timedelta(seconds=self.expires_in)


class TokenRefresher(Protocol):
    """Exchanges a refresh token for a new access token."""

    async def refresh(self, connection: Connection, refresh_token: str) -> TokenSet: ...


class VaultError(RuntimeError):
    pass


class ConnectionNotFoundError(VaultError):
    pass


class ReauthorizationRequiredError(VaultError):
    """The refresh token is gone or rejected — only the user can fix this.

    Expected on Gmail roughly weekly while the OAuth app is in Testing mode.
    """


_REFRESHERS: dict[enums.Provider, TokenRefresher] = {}


def register_refresher(provider: enums.Provider, refresher: TokenRefresher) -> None:
    _REFRESHERS[provider] = refresher


def get_refresher(provider: enums.Provider) -> TokenRefresher:
    try:
        return _REFRESHERS[provider]
    except KeyError:
        raise VaultError(
            f"No token refresher registered for {provider}. "
            "Register one at startup before using the vault for this provider."
        ) from None


# --- storage helpers ---------------------------------------------------------


def _store_refresh_token(connection: Connection, token: str | None) -> None:
    if token is None:
        return  # providers often omit it on refresh; keep the one we have
    sealed = seal(token)
    connection.refresh_token_ciphertext = sealed.ciphertext
    connection.refresh_token_key = sealed.wrapped_key


def _store_access_token(connection: Connection, token: str | None) -> None:
    if token is None:
        connection.access_token_ciphertext = None
        connection.access_token_key = None
        return
    sealed = seal(token)
    connection.access_token_ciphertext = sealed.ciphertext
    connection.access_token_key = sealed.wrapped_key


def read_refresh_token(connection: Connection) -> str | None:
    if not connection.refresh_token_ciphertext or not connection.refresh_token_key:
        return None
    return open_sealed(
        SealedSecret(connection.refresh_token_ciphertext, connection.refresh_token_key)
    )


def read_access_token(connection: Connection) -> str | None:
    if not connection.access_token_ciphertext or not connection.access_token_key:
        return None
    return open_sealed(
        SealedSecret(connection.access_token_ciphertext, connection.access_token_key)
    )


def apply_token_set(
    connection: Connection, tokens: TokenSet, *, now: datetime | None = None
) -> None:
    """Persist a token exchange onto a connection. Does not commit."""
    now = now or datetime.now(UTC)
    _store_access_token(connection, tokens.access_token)
    _store_refresh_token(connection, tokens.refresh_token)
    connection.access_expires_at = tokens.expires_at(now=now)
    if tokens.scopes:
        connection.scopes = tokens.scopes
    if tokens.api_domain:
        connection.api_domain = tokens.api_domain
    if tokens.accounts_url:
        connection.accounts_url = tokens.accounts_url
    connection.status = enums.ConnectionStatus.connected
    connection.last_error = None
    connection.last_ok_at = now


#: Providers whose tokens always carry an expiry. For these a null
#: `access_expires_at` means "we do not know", not "it lasts forever", and the
#: difference matters: assuming long-lived serves a dead token indefinitely and
#: every call 401s with nothing to indicate why.
EXPIRING_PROVIDERS = frozenset({enums.Provider.gmail, enums.Provider.zoho})


def needs_refresh(connection: Connection, *, now: datetime | None = None) -> bool:
    """True if the access token is absent, or close enough to expiry to be unsafe."""
    if not connection.access_token_ciphertext:
        return True
    if connection.access_expires_at is None:
        # WhatsApp's system-user token genuinely has no expiry; OAuth providers
        # always state one, so a missing value there is a gap to close, not a
        # promise to trust.
        return connection.provider in EXPIRING_PROVIDERS
    return connection.access_expires_at - (now or datetime.now(UTC)) <= REFRESH_MARGIN


# --- the public entry point --------------------------------------------------


async def get_connection(session: AsyncSession, user_id, provider: enums.Provider) -> Connection:
    result = await session.execute(
        select(Connection).where(
            Connection.user_id == user_id,
            Connection.provider == provider,
            Connection.status != enums.ConnectionStatus.revoked,
        )
    )
    connection = result.scalars().first()
    if connection is None:
        raise ConnectionNotFoundError(f"No {provider} connection for user {user_id}.")
    return connection


async def get_valid_access_token(
    session: AsyncSession,
    user_id,
    provider: enums.Provider,
    *,
    now: datetime | None = None,
    force: bool = False,
) -> str:
    """Return a usable access token, refreshing and persisting if necessary.

    `force` skips the expiry check entirely. Callers use it after a provider has
    rejected a token that we believed was still valid — the stored expiry is a
    claim, and the 401 is evidence against it.
    """
    now = now or datetime.now(UTC)
    connection = await get_connection(session, user_id, provider)

    if not force and not needs_refresh(connection, now=now):
        token = read_access_token(connection)
        if token:
            return token

    refresh_token = read_refresh_token(connection)
    if not refresh_token:
        connection.status = enums.ConnectionStatus.expired
        await session.flush()
        raise ReauthorizationRequiredError(
            f"The {provider} connection has no refresh token. The user must reconnect."
        )

    log.info(
        "vault.refresh.start",
        provider=provider.value,
        connection_id=str(connection.id),
        expires_at=connection.access_expires_at.isoformat()
        if connection.access_expires_at
        else None,
    )

    try:
        tokens = await get_refresher(provider).refresh(connection, refresh_token)
    except ReauthorizationRequiredError:
        connection.status = enums.ConnectionStatus.expired
        connection.last_error = "Refresh token rejected by the provider; reconnect required."
        await session.flush()
        log.warning("vault.refresh.reauth_required", provider=provider.value)
        raise
    except Exception as exc:
        connection.status = enums.ConnectionStatus.error
        connection.last_error = f"{type(exc).__name__}: {exc}"
        await session.flush()
        log.error("vault.refresh.failed", provider=provider.value, error_type=type(exc).__name__)
        raise

    apply_token_set(connection, tokens, now=now)
    await session.flush()
    log.info("vault.refresh.ok", provider=provider.value, connection_id=str(connection.id))
    return tokens.access_token
