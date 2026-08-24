"""Zoho CRM OAuth.

The thing that breaks Zoho integrations is the data centre. An org lives in one
of several regions (.com, .eu, .in, .com.au, .jp, .ca, .sa), each with its own
accounts server *and* its own API domain, and a token minted in one region is
worthless in another. The token response tells us both — `api_domain` always,
and the accounts server implied by where the exchange happened. We persist both
on the connection and every later call reads them from there.

`zohoapis.com` appears nowhere in this file as a destination.

Scopes are least-privilege by design: leads can be written, everything else is
read-only, and no scope grants deletion. There is deliberately no delete tool
anywhere in this system.
"""

from __future__ import annotations

from urllib.parse import urlencode, urlsplit

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

SCOPES = (
    "ZohoCRM.modules.leads.ALL",
    "ZohoCRM.modules.contacts.READ",
    "ZohoCRM.modules.deals.READ",
    "ZohoCRM.modules.notes.CREATE",
    "ZohoCRM.settings.modules.READ",
    "ZohoCRM.org.READ",
)

# Accounts server → human-readable region, for the UI.
DC_REGIONS = {
    "accounts.zoho.com": "US",
    "accounts.zoho.eu": "EU",
    "accounts.zoho.in": "India",
    "accounts.zoho.com.au": "Australia",
    "accounts.zoho.jp": "Japan",
    "accounts.zohocloud.ca": "Canada",
    "accounts.zoho.sa": "Saudi Arabia",
}


def region_for(accounts_url: str | None) -> str:
    if not accounts_url:
        return "unknown"
    return DC_REGIONS.get(urlsplit(accounts_url).netloc, "unknown")


class ZohoOAuthProvider(OAuthProvider):
    provider = enums.Provider.zoho
    scopes = SCOPES

    def is_configured(self) -> bool:
        settings = get_settings()
        return bool(settings.zoho_client_id and settings.zoho_client_secret)

    def _require_config(self) -> tuple[str, str, str, str]:
        settings = get_settings()
        if not self.is_configured():
            raise ProviderNotConfiguredError(
                "ZOHO_CLIENT_ID and ZOHO_CLIENT_SECRET are not set. See TODO.md."
            )
        return (
            settings.zoho_client_id or "",
            settings.zoho_client_secret or "",
            settings.redirect_uri_for("zoho"),
            settings.zoho_accounts_url.rstrip("/"),
        )

    def authorization_url(self, state: str) -> str:
        client_id, _, redirect_uri, accounts_url = self._require_config()
        params = {
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": ",".join(self.scopes),
            "access_type": "offline",
            # Without this, a second authorisation returns no refresh token.
            "prompt": "consent",
            "state": state,
        }
        return f"{accounts_url}/oauth/v2/auth?{urlencode(params)}"

    async def _token_request(self, payload: dict[str, str], accounts_url: str) -> dict:
        async with httpx.AsyncClient(timeout=20.0) as client:
            response = await client.post(f"{accounts_url}/oauth/v2/token", data=payload)

        if not response.is_success:
            raise OAuthExchangeError(f"Zoho token endpoint returned {response.status_code}")

        data = response.json()
        # Zoho reports failures with HTTP 200 and an `error` key in the body.
        if "error" in data:
            error = data["error"]
            if error in {"invalid_code", "invalid_client", "invalid_grant"}:
                raise ReauthorizationRequiredError(f"Zoho rejected the grant ({error}).")
            raise OAuthExchangeError(f"Zoho returned an error: {error}")
        return data

    async def exchange_code(self, code: str) -> TokenSet:
        client_id, client_secret, redirect_uri, accounts_url = self._require_config()
        data = await self._token_request(
            {
                "code": code,
                "client_id": client_id,
                "client_secret": client_secret,
                "redirect_uri": redirect_uri,
                "grant_type": "authorization_code",
            },
            accounts_url,
        )
        return TokenSet(
            access_token=data["access_token"],
            refresh_token=data.get("refresh_token"),
            expires_in=data.get("expires_in"),
            scopes=list(self.scopes),
            # Persist what the response says, never what we assumed.
            api_domain=data.get("api_domain"),
            accounts_url=accounts_url,
        )

    async def refresh(self, connection: Connection, refresh_token: str) -> TokenSet:
        client_id, client_secret, _, default_accounts = self._require_config()
        # Refresh against the accounts server this connection was created on.
        accounts_url = (connection.accounts_url or default_accounts).rstrip("/")

        data = await self._token_request(
            {
                "refresh_token": refresh_token,
                "client_id": client_id,
                "client_secret": client_secret,
                "grant_type": "refresh_token",
            },
            accounts_url,
        )
        return TokenSet(
            access_token=data["access_token"],
            refresh_token=data.get("refresh_token"),
            expires_in=data.get("expires_in"),
            api_domain=data.get("api_domain") or connection.api_domain,
            accounts_url=accounts_url,
        )

    async def fetch_identity(self, tokens: TokenSet) -> Identity:
        """Read the org name from the API domain the token response gave us."""
        api_domain = tokens.api_domain
        if not api_domain:
            raise OAuthExchangeError(
                "Zoho did not return an api_domain; refusing to guess the data centre."
            )

        async with httpx.AsyncClient(timeout=20.0) as client:
            response = await client.get(
                f"{api_domain.rstrip('/')}/crm/v6/org",
                headers={"Authorization": f"Zoho-oauthtoken {tokens.access_token}"},
            )

        org_name = None
        org_id = None
        if response.is_success:
            orgs = response.json().get("org") or []
            if orgs:
                org_name = orgs[0].get("company_name")
                org_id = orgs[0].get("zgid")
        else:
            log.warning("zoho.org.fetch_failed", status_code=response.status_code)

        return Identity(
            external_account=org_id or api_domain,
            display_name=org_name,
            api_domain=api_domain,
            accounts_url=tokens.accounts_url,
        )

    async def revoke(self, connection: Connection, refresh_token: str) -> bool:
        accounts_url = (connection.accounts_url or get_settings().zoho_accounts_url).rstrip("/")
        async with httpx.AsyncClient(timeout=20.0) as client:
            response = await client.post(
                f"{accounts_url}/oauth/v2/token/revoke", params={"token": refresh_token}
            )
        if not response.is_success:
            log.warning("zoho.revoke.failed", status_code=response.status_code)
        return response.is_success
