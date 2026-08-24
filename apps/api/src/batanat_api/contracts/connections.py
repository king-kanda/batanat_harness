"""Connection contracts.

Note what is absent: there is no token field on any type in this file, and no
code path that could add one, because the API layer only ever constructs these
models — it never serialises a `Connection` row directly.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from batanat_api.db.enums import ConnectionStatus, Provider


class ConnectionView(BaseModel):
    """A connected provider, as shown on the Settings page."""

    id: uuid.UUID
    provider: Provider
    external_account: str = Field(description="Gmail address, Zoho org id, or WhatsApp number id.")
    display_name: str | None = None
    status: ConnectionStatus
    scopes: list[str] = Field(default_factory=list)

    access_expires_at: datetime | None = None
    expires_in_hours: float | None = Field(
        default=None, description="Negative once the access token has already expired."
    )
    can_refresh: bool = Field(
        default=False,
        description=(
            "A refresh token is stored, so the access token above renews itself. "
            "Whether one exists, never the token."
        ),
    )
    needs_reconnect: bool = Field(
        default=False,
        description="True when only the user can restore this connection.",
    )

    api_domain: str | None = Field(
        default=None, description="Zoho: the data-centre API host returned at authorisation."
    )
    region: str | None = Field(default=None, description="Zoho: human-readable data centre.")

    last_ok_at: datetime | None = None
    last_error: str | None = None
    connected_at: datetime


class ProviderStatus(BaseModel):
    """Whether a provider can be connected at all, given the environment."""

    provider: Provider
    configured: bool = Field(description="False when its credentials are missing from .env.")
    scopes: list[str] = Field(default_factory=list)


class WhatsAppLinkView(BaseModel):
    id: uuid.UUID
    phone_e164: str
    linked_at: datetime
    last_seen_at: datetime | None = None


class ConnectionsPage(BaseModel):
    """Everything the Settings → Connections screen needs, in one request."""

    connections: list[ConnectionView]
    providers: list[ProviderStatus]
    whatsapp_links: list[WhatsAppLinkView]
    whatsapp_business_number: str | None = None


class AuthorizationUrl(BaseModel):
    authorization_url: str


class PairingCodeView(BaseModel):
    """A freshly issued WhatsApp pairing code."""

    code: str
    expires_at: datetime
    business_number: str = Field(description="The shared number the user must text.")
    phone_e164: str = Field(description="The number this code was issued for, normalised.")
    message: str = Field(description="Exactly what the user should send, e.g. 'LINK ABCD2345'.")
    wa_me_url: str = Field(description="Deep link that opens WhatsApp with the message prefilled.")


class DisconnectResult(BaseModel):
    disconnected: bool
    upstream_revoked: bool = Field(
        description="False when the provider offers no revocation endpoint, or refused."
    )
