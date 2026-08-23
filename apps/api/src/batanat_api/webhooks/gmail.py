"""Gmail Pub/Sub push endpoint.

Google POSTs a base64 envelope containing `{emailAddress, historyId}` and signs
the request with an OIDC bearer token. We verify that token before doing
anything: the URL is public, and without verification anyone who finds it can
make us re-sync on demand.

Delivery is at-least-once and unordered, so the endpoint is deliberately dumb:
it validates, debounces, and returns 200. Returning anything else makes Pub/Sub
retry, and a retry cannot fix a malformed notification.

Debounce: a busy inbox produces a notification per message. Processing each
separately would mean twenty agent runs for twenty emails. A 60-second Redis
window collapses them into one.
"""

from __future__ import annotations

import base64
import json
from typing import Any

from fastapi import APIRouter, Header, Request, Response

from batanat_api.config import get_settings
from batanat_api.core.deps import SessionDep
from batanat_api.core.logging import get_logger

log = get_logger(__name__)

router = APIRouter(prefix="/api/webhooks/gmail", tags=["webhooks"])

DEBOUNCE_SECONDS = 60
DEBOUNCE_KEY = "gmail:debounce:{email}"


def decode_envelope(payload: dict[str, Any]) -> dict[str, Any] | None:
    """Unwrap Pub/Sub's base64 message body."""
    data = (payload.get("message") or {}).get("data")
    if not data:
        return None
    try:
        return json.loads(base64.b64decode(data).decode())
    except Exception:  # noqa: BLE001
        return None


async def verify_oidc_token(authorization: str | None) -> bool:
    """Verify Google's signed push token.

    Checks the signature against Google's public keys, and that the service
    account and audience are the ones we configured. Without this the endpoint
    is an open trigger.
    """
    settings = get_settings()
    if not settings.gmail_pubsub_service_account:
        # Not configured: refuse rather than accept anything. Fail closed.
        log.error("gmail.webhook.no_service_account_configured")
        return False

    if not authorization or not authorization.startswith("Bearer "):
        return False

    token = authorization.removeprefix("Bearer ")
    try:
        from google.auth.transport import requests as google_requests
        from google.oauth2 import id_token

        claims = id_token.verify_oauth2_token(
            token,
            google_requests.Request(),
            audience=settings.gmail_pubsub_audience or None,
        )
    except ImportError:
        log.error(
            "gmail.webhook.verification_unavailable",
            detail="google-auth is not installed; refusing the push.",
        )
        return False
    except Exception as exc:  # noqa: BLE001
        log.warning("gmail.webhook.bad_token", error_type=type(exc).__name__)
        return False

    if claims.get("email") != settings.gmail_pubsub_service_account:
        log.warning("gmail.webhook.wrong_service_account")
        return False
    if not claims.get("email_verified", False):
        return False
    return True


async def should_process(email_address: str) -> bool:
    """Collapse a burst of notifications into one run.

    Returns True for the first notification in the window and False for the
    rest. The run that does happen syncs from the stored cursor, so it picks up
    every message the suppressed notifications referred to.
    """
    from redis.asyncio import from_url

    client = from_url(get_settings().redis_url)
    try:
        # SET NX is the whole debounce: first caller wins the window.
        acquired = await client.set(
            DEBOUNCE_KEY.format(email=email_address), "1", ex=DEBOUNCE_SECONDS, nx=True
        )
        return bool(acquired)
    except Exception:  # noqa: BLE001 — Redis down must not stop ingestion
        log.warning("gmail.debounce.unavailable")
        return True
    finally:
        await client.aclose()


@router.post("", include_in_schema=False, summary="Gmail push notification")
async def push(
    request: Request,
    session: SessionDep,
    authorization: str | None = Header(default=None),
) -> Response:
    if not await verify_oidc_token(authorization):
        # 401 rather than 403: Pub/Sub treats both as failure, and the log line
        # is what matters here.
        return Response(status_code=401)

    payload = await request.json()
    envelope = decode_envelope(payload)
    if not envelope:
        log.warning("gmail.webhook.undecodable")
        return Response(status_code=200)  # a retry will not help

    email_address = envelope.get("emailAddress")
    history_id = envelope.get("historyId")
    if not email_address:
        return Response(status_code=200)

    if not await should_process(email_address):
        log.info("gmail.webhook.debounced", history_id=history_id)
        return Response(status_code=200)

    from batanat_api.triggers.gmail_trigger import handle_notification

    try:
        await handle_notification(session, email_address, history_id)
    except Exception as exc:  # noqa: BLE001
        # Never 500 at Pub/Sub: it retries hard, and the failure is ours.
        log.exception("gmail.webhook.processing_failed", error_type=type(exc).__name__)

    return Response(status_code=200)
