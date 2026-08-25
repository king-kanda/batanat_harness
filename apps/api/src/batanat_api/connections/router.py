"""Connections API.

The OAuth callbacks redirect back to the web app rather than returning JSON —
the browser lands here from the provider, and the user should end up looking at
the Settings page, not at a payload. Failures redirect too, carrying an `error`
query parameter the UI renders.
"""

from __future__ import annotations

import uuid
from urllib.parse import urlencode

from fastapi import APIRouter, Body, HTTPException, Query, Response, status
from fastapi.responses import RedirectResponse
from starlette.background import BackgroundTask

from batanat_api.config import get_settings
from batanat_api.connections import service, state, whatsapp
from batanat_api.connections.providers.base import (
    OAuthExchangeError,
    ProviderNotConfiguredError,
)
from batanat_api.contracts.connections import (
    AuthorizationUrl,
    ConnectionsPage,
    DisconnectResult,
    PairingCodeView,
    WhatsAppLinkView,
)
from batanat_api.core.deps import CurrentUser, SessionDep
from batanat_api.core.logging import get_logger
from batanat_api.db import enums

log = get_logger(__name__)

router = APIRouter(prefix="/api/connections", tags=["connections"])

OAUTH_PROVIDERS = {enums.Provider.gmail, enums.Provider.zoho}


def _settings_url(**params: str) -> str:
    base = f"{get_settings().web_public_url.rstrip('/')}/settings/connections"
    return f"{base}?{urlencode(params)}" if params else base


@router.get("", response_model=ConnectionsPage, summary="Everything the Settings page needs")
async def list_all(session: SessionDep, user: CurrentUser) -> ConnectionsPage:
    settings = get_settings()
    links = await service.list_whatsapp_links(session, user.id)
    return ConnectionsPage(
        connections=await service.list_connections(session, user.id),
        providers=service.provider_statuses(),
        whatsapp_links=[
            WhatsAppLinkView(
                id=link.id,
                phone_e164=link.phone_e164,
                linked_at=link.linked_at,
                last_seen_at=link.last_seen_at,
            )
            for link in links
        ],
        whatsapp_business_number=settings.whatsapp_business_number or None,
    )


@router.post(
    "/{provider}/authorize",
    response_model=AuthorizationUrl,
    summary="Begin the OAuth flow",
)
async def authorize(provider: enums.Provider, user: CurrentUser) -> AuthorizationUrl:
    if provider not in OAUTH_PROVIDERS:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"{provider} does not use OAuth.")

    implementation = service.get_provider(provider)
    if not implementation.is_configured():
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            f"{provider} is not configured. Set its client id and secret in .env — see TODO.md.",
        )

    token = await state.issue(user.id, provider, return_to=_settings_url())
    return AuthorizationUrl(authorization_url=implementation.authorization_url(token))


@router.get("/{provider}/callback", summary="OAuth redirect target", include_in_schema=False)
async def callback(
    provider: enums.Provider,
    session: SessionDep,
    code: str | None = Query(default=None),
    state_token: str | None = Query(default=None, alias="state"),
    error: str | None = Query(default=None),
) -> RedirectResponse:
    if error:
        # The user declined, or the provider refused. Not an exception.
        log.info("connection.callback.declined", provider=provider.value, error=error)
        return RedirectResponse(_settings_url(error=error), status_code=302)

    try:
        oauth_state = await state.consume(state_token or "")
    except state.InvalidStateError as exc:
        log.warning("connection.callback.bad_state", provider=provider.value)
        return RedirectResponse(_settings_url(error=str(exc)), status_code=302)

    if oauth_state.provider is not provider:
        log.warning("connection.callback.provider_mismatch", provider=provider.value)
        return RedirectResponse(_settings_url(error="Provider mismatch."), status_code=302)

    if not code:
        return RedirectResponse(_settings_url(error="No authorization code."), status_code=302)

    try:
        await service.complete_authorization(session, oauth_state.user_id, provider, code)
    except (OAuthExchangeError, ProviderNotConfiguredError) as exc:
        log.error("connection.callback.exchange_failed", provider=provider.value, detail=str(exc))
        return RedirectResponse(_settings_url(error=str(exc)), status_code=302)

    # Storing the token is not connecting. Gmail needs a `users.watch` before
    # Google publishes anything, and a backfill before the inbox shows anything
    # — without both, a correctly configured integration looks dead.
    #
    # Deliberately inline rather than backgrounded: the session and its
    # transaction belong to this request, and handing them to a task that
    # outlives it is how you get a connection used after close. A backfill of
    # 30 days caps at 200 messages, which is seconds, and the redirect waiting
    # for it is the difference between landing on a populated screen and an
    # empty one.
    if provider is enums.Provider.gmail:
        from batanat_api.gmail.setup import prepare_mailbox

        setup = await prepare_mailbox(session, oauth_state.user_id)
        for problem in setup.problems:
            log.warning("connection.callback.setup_incomplete", provider="gmail", detail=problem)

        # Classifying runs *after* the response, on its own session. The import
        # above is a handful of HTTP calls; classifying is a model call per 20
        # messages, which would leave the browser on a blank redirect for
        # minutes. The session and its transaction belong to this request, so a
        # task that outlives it must open its own.
        classify = BackgroundTask(_classify_after_connect, oauth_state.user_id)

        if setup.problems:
            # Connected, but not fully working. Say which, rather than showing
            # a success screen over a mailbox that will never receive anything.
            return RedirectResponse(
                _settings_url(connected=provider.value, error="; ".join(setup.problems)),
                status_code=302,
                background=classify,
            )
        return RedirectResponse(
            _settings_url(connected=provider.value), status_code=302, background=classify
        )

    return RedirectResponse(_settings_url(connected=provider.value), status_code=302)


async def _classify_after_connect(user_id: uuid.UUID) -> None:
    """Give the just-imported mail a verdict. Never raises — the account is
    already connected, and the nightly sweep retries whatever this misses."""
    from batanat_api.db.session import session_scope
    from batanat_api.triggers.gmail_trigger import classify_pending

    try:
        async with session_scope() as session:
            count = await classify_pending(session, user_id)
        log.info("connection.callback.backlog_classified", count=count)
    except Exception as exc:  # noqa: BLE001
        log.warning("connection.callback.classify_failed", error_type=type(exc).__name__)


@router.delete("/{connection_id}", response_model=DisconnectResult, summary="Disconnect")
async def disconnect(
    connection_id: uuid.UUID, session: SessionDep, user: CurrentUser
) -> DisconnectResult:
    try:
        revoked = await service.disconnect(session, user.id, connection_id)
    except LookupError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such connection.") from None
    return DisconnectResult(disconnected=True, upstream_revoked=revoked)


# --- WhatsApp pairing --------------------------------------------------------


@router.post("/whatsapp/pairing-code", response_model=PairingCodeView, summary="Issue a code")
async def create_pairing_code(
    session: SessionDep,
    user: CurrentUser,
    phone: str = Body(embed=True, description="The number to link, as the user typed it."),
) -> PairingCodeView:
    """Issue a pairing code for one specific number.

    The number is taken first and the code is bound to it, so a code read off
    someone's screen cannot be redeemed from a different handset.
    """
    settings = get_settings()
    business_number = settings.whatsapp_business_number
    if not business_number:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "WHATSAPP_BUSINESS_NUMBER is not set — see TODO.md.",
        )

    try:
        phone_e164 = whatsapp.normalise_phone(phone)
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from None

    try:
        issued = await whatsapp.issue_code(session, user.id, phone_e164=phone_e164)
    except whatsapp.RateLimitedError as exc:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, str(exc)) from None

    return PairingCodeView(
        code=issued.code,
        expires_at=issued.expires_at,
        business_number=business_number,
        phone_e164=phone_e164,
        message=f"LINK {issued.code}",
        wa_me_url=whatsapp.wa_me_url(business_number, issued.code),
    )


@router.delete("/whatsapp/links/{link_id}", status_code=204, summary="Unlink a number")
async def unlink_number(link_id: uuid.UUID, session: SessionDep, user: CurrentUser) -> Response:
    try:
        await whatsapp.unlink(session, user.id, link_id)
    except LookupError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such linked number.") from None
    return Response(status_code=204)
