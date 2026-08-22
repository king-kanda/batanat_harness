"""The OAuth provider interface.

Google and Zoho differ in almost every detail — where the accounts server
lives, whether the API domain is fixed, what a revocation looks like, what they
return when a refresh token dies. They agree on the shape of the dance, so that
shape is the interface and everything else is per-provider.

Each provider is exercised against the real endpoints; none of it can be
verified end to end without the client's own OAuth clients (see TODO.md).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from batanat_api.db import enums
from batanat_api.db.models import Connection
from batanat_api.security.token_vault import TokenSet


@dataclass(frozen=True, slots=True)
class Identity:
    """Who the tokens belong to, as the provider describes them."""

    external_account: str
    display_name: str | None = None
    api_domain: str | None = None
    accounts_url: str | None = None


class ProviderNotConfiguredError(RuntimeError):
    """The client id/secret for this provider are absent from the environment."""


class OAuthExchangeError(RuntimeError):
    """The provider rejected an authorization code or refresh token."""


class OAuthProvider(ABC):
    provider: enums.Provider
    scopes: tuple[str, ...]

    @abstractmethod
    def is_configured(self) -> bool:
        """False when the credentials are missing, so the UI can say so plainly."""

    @abstractmethod
    def authorization_url(self, state: str) -> str:
        """Where to send the browser to begin consent."""

    @abstractmethod
    async def exchange_code(self, code: str) -> TokenSet:
        """Trade an authorization code for tokens."""

    @abstractmethod
    async def refresh(self, connection: Connection, refresh_token: str) -> TokenSet:
        """Trade a refresh token for a new access token. Used by the token vault."""

    @abstractmethod
    async def fetch_identity(self, tokens: TokenSet) -> Identity:
        """Ask the provider who these tokens belong to."""

    async def revoke(self, connection: Connection, refresh_token: str) -> bool:
        """Revoke upstream if the provider supports it.

        Returns False when the provider offers no revocation endpoint, so
        disconnect can tell the user whether the grant is really gone.
        """
        return False
