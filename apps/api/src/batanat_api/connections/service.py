"""Connection lifecycle: connect, describe, disconnect.

The provider objects know how to talk to Google and Zoho; this module owns what
happens to our own database around those calls, and is the only place that
turns a `Connection` row into something the frontend may see.

That last point matters: `to_public()` is the boundary. Token columns exist on
the model and are never present in what leaves this module.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from batanat_api.connections.providers.base import OAuthProvider
from batanat_api.connections.providers.google import GoogleOAuthProvider
from batanat_api.connections.providers.zoho import ZohoOAuthProvider, region_for
from batanat_api.contracts.connections import ConnectionView, ProviderStatus
from batanat_api.core.logging import get_logger
from batanat_api.db import enums
from batanat_api.db.models import Connection, WhatsAppLink
from batanat_api.security import token_vault
from batanat_api.security.token_vault import apply_token_set, read_refresh_token

log = get_logger(__name__)

PROVIDERS: dict[enums.Provider, OAuthProvider] = {
    enums.Provider.gmail: GoogleOAuthProvider(),
    enums.Provider.zoho: ZohoOAuthProvider(),
}


def register_refreshers() -> None:
    """Hand the OAuth providers to the token vault. Called once at startup."""
    for provider, implementation in PROVIDERS.items():
        token_vault.register_refresher(provider, implementation)


def get_provider(provider: enums.Provider) -> OAuthProvider:
    try:
        return PROVIDERS[provider]
    except KeyError:
        raise ValueError(f"{provider} does not use the OAuth flow.") from None


# --- reading -----------------------------------------------------------------


def to_public(connection: Connection) -> ConnectionView:
    """The only representation of a connection the frontend ever receives.

    Tokens are not omitted by convention here — they are simply not fields of
    the type being constructed, so a future edit cannot leak one by accident.
    """
    expires_at = connection.access_expires_at
    now = datetime.now(UTC)
    expires_in_hours = round((expires_at - now).total_seconds() / 3600, 1) if expires_at else None

    return ConnectionView(
        id=connection.id,
        provider=connection.provider,
        external_account=connection.external_account,
        display_name=connection.display_name,
        status=connection.status,
        scopes=list(connection.scopes or []),
        access_expires_at=expires_at,
        expires_in_hours=expires_in_hours,
        # Whether a refresh token exists, never the token itself. Without this
        # the UI cannot tell a one-hour token that renews itself from one that
        # is about to strand the connection — and Google's are always one hour.
        can_refresh=bool(connection.refresh_token_ciphertext),
        needs_reconnect=connection.status
        in (enums.ConnectionStatus.expired, enums.ConnectionStatus.revoked),
        api_domain=connection.api_domain,
        region=region_for(connection.accounts_url)
        if connection.provider is enums.Provider.zoho
        else None,
        last_ok_at=connection.last_ok_at,
        last_error=connection.last_error,
        connected_at=connection.created_at,
    )


async def list_connections(session: AsyncSession, user_id: uuid.UUID) -> list[ConnectionView]:
    rows = (
        (
            await session.execute(
                select(Connection)
                .where(
                    Connection.user_id == user_id,
                    Connection.status != enums.ConnectionStatus.revoked,
                )
                .order_by(Connection.provider)
            )
        )
        .scalars()
        .all()
    )
    return [to_public(row) for row in rows]


async def list_whatsapp_links(session: AsyncSession, user_id: uuid.UUID) -> list[WhatsAppLink]:
    return list(
        (
            await session.execute(
                select(WhatsAppLink)
                .where(WhatsAppLink.user_id == user_id, WhatsAppLink.is_active.is_(True))
                .order_by(WhatsAppLink.linked_at.desc())
            )
        )
        .scalars()
        .all()
    )


def provider_statuses() -> list[ProviderStatus]:
    """What the Settings page shows for providers that are not yet connected."""
    from batanat_api.config import get_settings

    settings = get_settings()
    statuses = [
        ProviderStatus(
            provider=provider,
            configured=implementation.is_configured(),
            scopes=list(implementation.scopes),
        )
        for provider, implementation in PROVIDERS.items()
    ]
    statuses.append(
        ProviderStatus(
            provider=enums.Provider.whatsapp,
            configured=bool(settings.whatsapp_access_token and settings.whatsapp_phone_number_id),
            scopes=[],
        )
    )
    return statuses


# --- writing -----------------------------------------------------------------


async def complete_authorization(
    session: AsyncSession,
    user_id: uuid.UUID,
    provider: enums.Provider,
    code: str,
) -> Connection:
    """Exchange the code, identify the account, and upsert the connection.

    Re-authorising an account we already hold updates that row rather than
    creating a second one — the unique constraint on
    (user_id, provider, external_account) is what makes that safe.
    """
    implementation = get_provider(provider)

    tokens = await implementation.exchange_code(code)
    identity = await implementation.fetch_identity(tokens)

    if identity.api_domain:
        tokens.api_domain = identity.api_domain
    if identity.accounts_url:
        tokens.accounts_url = identity.accounts_url

    connection = (
        (
            await session.execute(
                select(Connection).where(
                    Connection.user_id == user_id,
                    Connection.provider == provider,
                    Connection.external_account == identity.external_account,
                )
            )
        )
        .scalars()
        .first()
    )

    if connection is None:
        connection = Connection(
            user_id=user_id,
            provider=provider,
            external_account=identity.external_account,
        )
        session.add(connection)

    connection.display_name = identity.display_name
    apply_token_set(connection, tokens)
    await session.flush()

    log.info(
        "connection.authorized",
        provider=provider.value,
        connection_id=str(connection.id),
        external_account=identity.external_account,
        expires_at=connection.access_expires_at.isoformat()
        if connection.access_expires_at
        else None,
    )
    return connection


async def disconnect(session: AsyncSession, user_id: uuid.UUID, connection_id: uuid.UUID) -> bool:
    """Revoke upstream where possible, then clear every stored secret.

    Returns whether the upstream revocation succeeded. Local state is cleared
    either way: refusing to disconnect because a remote call failed would leave
    the user stuck with a connection they have asked to remove.
    """
    connection = (
        (
            await session.execute(
                select(Connection).where(
                    Connection.id == connection_id, Connection.user_id == user_id
                )
            )
        )
        .scalars()
        .first()
    )
    if connection is None:
        raise LookupError("No such connection.")

    revoked = False
    refresh_token = read_refresh_token(connection)
    if refresh_token and connection.provider in PROVIDERS:
        try:
            revoked = await get_provider(connection.provider).revoke(connection, refresh_token)
        except Exception as exc:  # noqa: BLE001 — never block a disconnect
            log.warning(
                "connection.revoke.failed",
                provider=connection.provider.value,
                error_type=type(exc).__name__,
            )

    connection.refresh_token_ciphertext = None
    connection.refresh_token_key = None
    connection.access_token_ciphertext = None
    connection.access_token_key = None
    connection.access_expires_at = None
    connection.status = enums.ConnectionStatus.revoked
    connection.last_error = None
    await session.flush()

    log.info(
        "connection.disconnected",
        provider=connection.provider.value,
        connection_id=str(connection.id),
        upstream_revoked=revoked,
    )
    return revoked
