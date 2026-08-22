"""Google / Gmail OAuth.

Two details drive everything here.

`access_type=offline` with `prompt=consent` is what makes Google issue a refresh
token. Without `prompt=consent` a user who has authorised before gets an access
token and no refresh token, and the connection silently dies an hour later.

Google only returns the refresh token on the *first* exchange, and never on a
refresh. The token vault keeps the stored one when a response omits it — see
`apply_token_set`.

While the OAuth app is in Testing mode, Google expires refresh tokens after
roughly seven days. That surfaces here as `invalid_grant`, which we translate
into `ReauthorizationRequiredError` so the UI can ask for a reconnect instead of
retrying forever.
"""

from __future__ import annotations

from urllib.parse import urlencode

import httpx

from batanat_api.config import get_settings
from batanat_api.connections.providers.base import (
    Identity,
    OAuthExchangeError,
    OAuthProvider,
    ProviderNotConfiguredError,
)
from batanat_api.core.logging import get_logger
from batanat_api.db import enums
from batanat_api.db.models import Connection
from batanat_api.security.token_vault import ReauthorizationRequiredError, TokenSet

log = get_logger(__name__)

AUTH_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"
REVOKE_ENDPOINT = "https://oauth2.googleapis.com/revoke"
USERINFO_ENDPOINT = "https://www.googleapis.com/oauth2/v2/userinfo"

SCOPES = (
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/userinfo.email",
)


class GoogleOAuthProvider(OAuthProvider):
    provider = enums.Provider.gmail
    scopes = SCOPES

    def is_configured(self) -> bool:
        settings = get_settings()
        return bool(settings.google_client_id and settings.google_client_secret)

    def _require_config(self) -> tuple[str, str, str]:
        settings = get_settings()
        if not self.is_configured():
            raise ProviderNotConfiguredError(
                "GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET are not set. See TODO.md."
            )
        return (
            settings.google_client_id or "",
            settings.google_client_secret or "",
            settings.google_redirect_uri,
        )

    def authorization_url(self, state: str) -> str:
        client_id, _, redirect_uri = self._require_config()
        params = {
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": " ".join(self.scopes),
            # Both are required to be issued a refresh token.
            "access_type": "offline",
            "prompt": "consent",
            "include_granted_scopes": "true",
            "state": state,
        }
        return f"{AUTH_ENDPOINT}?{urlencode(params)}"

    async def _token_request(self, payload: dict[str, str]) -> dict:
        async with httpx.AsyncClient(timeout=20.0) as client:
            response = await client.post(TOKEN_ENDPOINT, data=payload)

        if response.is_success:
            return response.json()

        body = (
            response.json()
            if response.headers.get("content-type", "").startswith("application/json")
            else {}
        )
        error = body.get("error", "unknown_error")

        # invalid_grant means the refresh token is dead — revoked, expired, or
        # aged out by Testing mode. Only the user can fix it.
        if error == "invalid_grant":
            raise ReauthorizationRequiredError("Google rejected the grant (invalid_grant).")

        raise OAuthExchangeError(f"Google token endpoint returned {response.status_code}: {error}")

    async def exchange_code(self, code: str) -> TokenSet:
        client_id, client_secret, redirect_uri = self._require_config()
        data = await self._token_request(
            {
                "code": code,
                "client_id": client_id,
                "client_secret": client_secret,
                "redirect_uri": redirect_uri,
                "grant_type": "authorization_code",
            }
        )
        return TokenSet(
            access_token=data["access_token"],
            refresh_token=data.get("refresh_token"),
            expires_in=data.get("expires_in"),
            scopes=data.get("scope", "").split() or list(self.scopes),
        )

    async def refresh(self, connection: Connection, refresh_token: str) -> TokenSet:
        client_id, client_secret, _ = self._require_config()
        data = await self._token_request(
            {
                "refresh_token": refresh_token,
                "client_id": client_id,
                "client_secret": client_secret,
                "grant_type": "refresh_token",
            }
        )
        return TokenSet(
            access_token=data["access_token"],
            # Google does not re-issue it; the vault keeps the stored one.
            refresh_token=data.get("refresh_token"),
            expires_in=data.get("expires_in"),
            scopes=data.get("scope", "").split(),
        )

    async def fetch_identity(self, tokens: TokenSet) -> Identity:
        async with httpx.AsyncClient(timeout=20.0) as client:
            response = await client.get(
                USERINFO_ENDPOINT,
                headers={"Authorization": f"Bearer {tokens.access_token}"},
            )
        response.raise_for_status()
        profile = response.json()
        return Identity(
            external_account=profile["email"],
            display_name=profile.get("name") or profile["email"],
        )

    async def revoke(self, connection: Connection, refresh_token: str) -> bool:
        """Revoking the refresh token invalidates the whole grant."""
        async with httpx.AsyncClient(timeout=20.0) as client:
            response = await client.post(REVOKE_ENDPOINT, data={"token": refresh_token})
        if not response.is_success:
            log.warning("google.revoke.failed", status_code=response.status_code)
        return response.is_success
