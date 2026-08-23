"""Connections: OAuth request construction, secret hygiene, and pairing security.

The OAuth exchanges themselves cannot be tested without the client's own
credentials (TODO.md). What *is* testable, and matters most, is everything
around them: that the authorization URLs ask for the right things, that Zoho's
data centre is never assumed, that no token can reach the frontend, and that
the pairing flow cannot be brute-forced or used to hijack another user's alerts.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlsplit

import pytest

from batanat_api.config import get_settings
from batanat_api.connections import service, whatsapp
from batanat_api.connections.providers.base import ProviderNotConfiguredError
from batanat_api.connections.providers.google import GoogleOAuthProvider
from batanat_api.connections.providers.zoho import ZohoOAuthProvider, region_for
from batanat_api.db import enums
from batanat_api.db.models import Connection, User, WhatsAppLink
from batanat_api.security.token_vault import TokenSet, apply_token_set


@pytest.fixture
def google(monkeypatch: pytest.MonkeyPatch) -> GoogleOAuthProvider:
    settings = get_settings()
    monkeypatch.setattr(settings, "google_client_id", "test-client-id")
    monkeypatch.setattr(settings, "google_client_secret", "test-secret")
    return GoogleOAuthProvider()


@pytest.fixture
def zoho(monkeypatch: pytest.MonkeyPatch) -> ZohoOAuthProvider:
    settings = get_settings()
    monkeypatch.setattr(settings, "zoho_client_id", "test-client-id")
    monkeypatch.setattr(settings, "zoho_client_secret", "test-secret")
    return ZohoOAuthProvider()


def _params(url: str) -> dict[str, str]:
    return {k: v[0] for k, v in parse_qs(urlsplit(url).query).items()}


# --- Google ------------------------------------------------------------------


def test_google_asks_for_a_refresh_token(google: GoogleOAuthProvider) -> None:
    """Without both of these, Google issues no refresh token and the link dies in an hour."""
    params = _params(google.authorization_url("state-123"))
    assert params["access_type"] == "offline"
    assert params["prompt"] == "consent"
    assert params["state"] == "state-123"
    assert params["response_type"] == "code"


def test_google_requests_only_read_scopes(google: GoogleOAuthProvider) -> None:
    scopes = _params(google.authorization_url("s"))["scope"].split()
    assert "https://www.googleapis.com/auth/gmail.readonly" in scopes
    assert not any("modify" in s or "send" in s or "compose" in s for s in scopes)


def test_unconfigured_provider_refuses_rather_than_building_a_broken_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(get_settings(), "google_client_id", None)
    monkeypatch.setattr(get_settings(), "google_client_secret", None)
    provider = GoogleOAuthProvider()
    assert provider.is_configured() is False
    with pytest.raises(ProviderNotConfiguredError):
        provider.authorization_url("s")


# --- Zoho: the data-centre trap ----------------------------------------------


def test_zoho_authorization_uses_the_configured_accounts_server(
    zoho: ZohoOAuthProvider, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(get_settings(), "zoho_accounts_url", "https://accounts.zoho.eu")
    url = zoho.authorization_url("s")
    assert url.startswith("https://accounts.zoho.eu/oauth/v2/auth")


def test_zoho_scopes_are_least_privilege(zoho: ZohoOAuthProvider) -> None:
    scopes = _params(zoho.authorization_url("s"))["scope"].split(",")
    assert "ZohoCRM.modules.leads.ALL" in scopes
    assert "ZohoCRM.modules.ALL" not in scopes
    # Nothing may grant deletion — there is no delete tool anywhere in this system.
    assert not any("DELETE" in s.upper() for s in scopes)
    # Everything except leads and note-creation is read-only.
    assert {"ZohoCRM.modules.contacts.READ", "ZohoCRM.modules.deals.READ"} <= set(scopes)


async def test_zoho_refresh_targets_the_connection_s_own_accounts_server(
    zoho: ZohoOAuthProvider, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A token minted in the EU is worthless against the US endpoint."""
    monkeypatch.setattr(get_settings(), "zoho_accounts_url", "https://accounts.zoho.com")
    connection = Connection(
        user_id=uuid.uuid4(),
        provider=enums.Provider.zoho,
        external_account="org",
        accounts_url="https://accounts.zoho.eu",
        scopes=[],
    )

    captured: dict[str, str] = {}

    async def fake_token_request(payload, accounts_url):
        captured["accounts_url"] = accounts_url
        return {"access_token": "a", "expires_in": 3600, "api_domain": "https://www.zohoapis.eu"}

    monkeypatch.setattr(zoho, "_token_request", fake_token_request)

    tokens = await zoho.refresh(connection, "refresh")

    assert captured["accounts_url"] == "https://accounts.zoho.eu"
    assert tokens.api_domain == "https://www.zohoapis.eu"


@pytest.mark.parametrize(
    ("accounts_url", "expected"),
    [
        ("https://accounts.zoho.com", "US"),
        ("https://accounts.zoho.eu", "EU"),
        ("https://accounts.zoho.in", "India"),
        ("https://accounts.example.com", "unknown"),
        (None, "unknown"),
    ],
)
def test_region_is_derived_from_the_accounts_server(accounts_url, expected) -> None:
    assert region_for(accounts_url) == expected


async def test_zoho_will_not_guess_an_api_domain() -> None:
    """Guessing zohoapis.com is the single most common way this integration breaks."""
    from batanat_api.connections.providers.base import OAuthExchangeError

    provider = ZohoOAuthProvider()
    tokens = TokenSet(access_token="a", api_domain=None)

    with pytest.raises(OAuthExchangeError, match="api_domain"):
        await provider.fetch_identity(tokens)


# --- the frontend boundary ---------------------------------------------------


def test_the_public_view_cannot_carry_a_token() -> None:
    connection = Connection(
        id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        provider=enums.Provider.gmail,
        external_account="martin@batanat.co.ke",
        scopes=["gmail.readonly"],
        status=enums.ConnectionStatus.connected,
        created_at=datetime.now(UTC),
    )
    apply_token_set(
        connection,
        TokenSet(access_token="ya29.SECRET", refresh_token="1//SECRET", expires_in=3600),
    )

    serialised = json.dumps(service.to_public(connection).model_dump(mode="json"))

    assert "ya29.SECRET" not in serialised
    assert "1//SECRET" not in serialised
    assert "token" not in serialised.lower()


def test_expiry_is_surfaced_so_the_ui_can_warn() -> None:
    connection = Connection(
        id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        provider=enums.Provider.gmail,
        external_account="a@b.c",
        scopes=[],
        status=enums.ConnectionStatus.expired,
        created_at=datetime.now(UTC),
        access_expires_at=datetime.now(UTC) - timedelta(hours=2),
    )
    view = service.to_public(connection)
    assert view.needs_reconnect is True
    assert view.expires_in_hours is not None and view.expires_in_hours < 0


# --- WhatsApp pairing --------------------------------------------------------


def test_codes_avoid_visually_ambiguous_characters() -> None:
    """People read these off a screen and type them into a phone."""
    for _ in range(200):
        code = whatsapp.generate_code()
        assert len(code) == whatsapp.CODE_LENGTH
        assert not set(code) & set("O0I1")


def test_codes_are_not_predictable() -> None:
    assert len({whatsapp.generate_code() for _ in range(500)}) > 490


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        ("LINK ABCD2345", "ABCD2345"),
        ("link abcd2345", "ABCD2345"),
        ("  LINK   ABCD2345  ", "ABCD2345"),
        ("LINK ABCD234", None),  # too short
        ("LINK ABCD23456", None),  # too long
        ("LINK ABCD0345", None),  # excluded character
        ("please LINK ABCD2345", None),  # not a bare command
        ("APPROVE 3", None),
        ("", None),
    ],
)
def test_link_message_parsing(message: str, expected: str | None) -> None:
    assert whatsapp.parse_link_message(message) == expected


@pytest.mark.parametrize(
    ("typed", "expected"),
    [
        ("0712345678", "+254712345678"),
        ("+254712345678", "+254712345678"),
        ("254712345678", "+254712345678"),
        ("0712 345 678", "+254712345678"),
        ("712345678", "+254712345678"),
    ],
)
def test_phone_numbers_are_normalised_to_e164(typed: str, expected: str) -> None:
    """People type numbers five different ways; all of them are one number."""
    assert whatsapp.normalise_phone(typed) == expected


@pytest.mark.parametrize("typed", ["", "   ", "abc", "12"])
def test_unusable_phone_numbers_are_rejected(typed: str) -> None:
    with pytest.raises(ValueError):
        whatsapp.normalise_phone(typed)


async def test_a_code_is_bound_to_the_number_that_requested_it(session, user) -> None:
    """A code read off someone's screen is useless from another handset."""
    issued = await whatsapp.issue_code(session, user.id, phone_e164="+254712345678")
    await session.commit()

    wrong = await whatsapp.redeem_code(session, "+254799999999", issued.code)
    assert wrong.linked is False
    assert wrong.reply == whatsapp.GENERIC_FAILURE_REPLY

    right = await whatsapp.redeem_code(session, "+254712345678", issued.code)
    await session.commit()
    assert right.linked is True
    assert await whatsapp.resolve_user(session, "+254712345678") == user.id


def test_deep_link_prefills_the_exact_message() -> None:
    url = whatsapp.wa_me_url("+254700123456", "ABCD2345")
    assert url == "https://wa.me/254700123456?text=LINK%20ABCD2345"


async def test_a_valid_code_links_the_number(session, user) -> None:
    issued = await whatsapp.issue_code(session, user.id)
    await session.commit()

    result = await whatsapp.redeem_code(session, "+254700000010", issued.code)
    await session.commit()

    assert result.linked is True
    assert result.user_id == user.id
    assert await whatsapp.resolve_user(session, "+254700000010") == user.id


async def test_a_code_cannot_be_used_twice(session, user) -> None:
    issued = await whatsapp.issue_code(session, user.id)
    await session.commit()

    assert (await whatsapp.redeem_code(session, "+254700000011", issued.code)).linked is True
    await session.commit()

    second = await whatsapp.redeem_code(session, "+254700000012", issued.code)
    assert second.linked is False
    assert second.reply == whatsapp.GENERIC_FAILURE_REPLY


async def test_an_expired_code_is_refused(session, user) -> None:
    issued = await whatsapp.issue_code(session, user.id)
    await session.commit()

    later = datetime.now(UTC) + whatsapp.CODE_TTL + timedelta(seconds=1)
    result = await whatsapp.redeem_code(session, "+254700000013", issued.code, now=later)

    assert result.linked is False
    assert result.reply == whatsapp.GENERIC_FAILURE_REPLY


async def test_failures_are_indistinguishable_from_each_other(session, user) -> None:
    """The reply must not tell an attacker whether a code exists."""
    issued = await whatsapp.issue_code(session, user.id)
    await session.commit()
    await whatsapp.redeem_code(session, "+254700000014", issued.code)
    await session.commit()

    unknown = await whatsapp.redeem_code(session, "+254700000015", "ZZZZZZZZ")
    already_used = await whatsapp.redeem_code(session, "+254700000016", issued.code)
    expired_code = await whatsapp.issue_code(session, user.id)
    await session.commit()
    expired = await whatsapp.redeem_code(
        session,
        "+254700000017",
        expired_code.code,
        now=datetime.now(UTC) + timedelta(hours=1),
    )

    assert unknown.reply == already_used.reply == expired.reply == whatsapp.GENERIC_FAILURE_REPLY


async def test_a_number_linked_to_another_user_is_not_rebound(session, user) -> None:
    """Otherwise pairing someone else's number would redirect their alerts."""
    victim = User(email=f"victim-{uuid.uuid4().hex[:6]}@batanat.test")
    session.add(victim)
    await session.flush()
    session.add(
        WhatsAppLink(user_id=victim.id, phone_e164="+254700000020", linked_at=datetime.now(UTC))
    )
    await session.commit()

    issued = await whatsapp.issue_code(session, user.id)
    await session.commit()

    result = await whatsapp.redeem_code(session, "+254700000020", issued.code)
    await session.commit()

    assert result.linked is False
    assert "already linked" in result.reply
    # The victim keeps the binding.
    assert await whatsapp.resolve_user(session, "+254700000020") == victim.id


async def test_relinking_your_own_number_is_allowed(session, user) -> None:
    first = await whatsapp.issue_code(session, user.id)
    await session.commit()
    await whatsapp.redeem_code(session, "+254700000021", first.code)
    await session.commit()

    second = await whatsapp.issue_code(session, user.id)
    await session.commit()
    result = await whatsapp.redeem_code(session, "+254700000021", second.code)

    assert result.linked is True


async def test_pairing_attempts_are_rate_limited(session, user) -> None:
    """Eight characters is brute-forceable without this."""
    phone = f"+2547{uuid.uuid4().int % 100000000:08d}"
    replies = [
        await whatsapp.redeem_code(session, phone, "ZZZZZZZZ")
        for _ in range(whatsapp.MAX_ATTEMPTS_PER_PHONE_PER_HOUR + 2)
    ]
    assert all(r.linked is False for r in replies)
    # Once limited, the reply is still the same generic one — no signal.
    assert replies[-1].reply == whatsapp.GENERIC_FAILURE_REPLY


async def test_code_issuance_is_rate_limited(session, user) -> None:
    for _ in range(whatsapp.MAX_CODES_PER_USER_PER_HOUR):
        await whatsapp.issue_code(session, user.id)
    with pytest.raises(whatsapp.RateLimitedError):
        await whatsapp.issue_code(session, user.id)


async def test_unlinking_stops_attribution(session, user) -> None:
    issued = await whatsapp.issue_code(session, user.id)
    await session.commit()
    await whatsapp.redeem_code(session, "+254700000030", issued.code)
    await session.commit()

    link = (await service.list_whatsapp_links(session, user.id))[0]
    await whatsapp.unlink(session, user.id, link.id)
    await session.commit()

    assert await whatsapp.resolve_user(session, "+254700000030") is None


async def test_an_unpaired_number_resolves_to_nobody(session) -> None:
    assert await whatsapp.resolve_user(session, "+254799999999") is None


def test_phone_numbers_are_masked_in_logs() -> None:
    masked = whatsapp._mask("+254700123456")
    assert "700123" not in masked
    assert masked.startswith("+2547")
