"""Outbound email, via SendGrid.

The Gmail connection is `gmail.readonly` **by design** — the agent reads the
inbox and must never be able to send from it. So reports go out on a separate
credential with a separate blast radius: if the SendGrid key leaks, an attacker
can send email, but cannot read Martin's mail. Widening the Gmail scope would
have collapsed both capabilities into one token.

Recipients are configuration, not agent output. `REPORT_TO` and `REPORT_CC` are
read from the environment and nothing in a run can change them — an agent that
could choose its own recipients is an agent that can exfiltrate, and no prompt
or scraped page should be able to influence where a report lands.

Written on httpx rather than the `sendgrid` SDK: this is one POST, and the SDK
carries a lot of surface we would never use.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

import httpx

from batanat_api.config import get_settings
from batanat_api.core.logging import get_logger

log = get_logger(__name__)

SENDGRID_ENDPOINT = "https://api.sendgrid.com/v3/mail/send"

# Deliberately permissive: this is a typo check on operator-supplied config,
# not an attempt to validate the RFC.
EMAIL_PATTERN = re.compile(r"^[^@\s,;]+@[^@\s,;]+\.[^@\s,;]+$")


@dataclass(slots=True)
class Recipients:
    to: list[str] = field(default_factory=list)
    cc: list[str] = field(default_factory=list)
    invalid: list[str] = field(default_factory=list)

    @property
    def deliverable(self) -> bool:
        return bool(self.to)

    def describe(self) -> str:
        parts = [f"to={', '.join(self.to)}"] if self.to else []
        if self.cc:
            parts.append(f"cc={', '.join(self.cc)}")
        return "; ".join(parts) or "no recipients"


def parse_addresses(raw: str | None) -> tuple[list[str], list[str]]:
    """Split a comma-separated env value into (valid, invalid) addresses.

    One typo in `REPORT_CC` should not stop the report going to everyone else —
    the bad address is logged and named in the delivery record instead.
    """
    valid: list[str] = []
    invalid: list[str] = []

    for candidate in (raw or "").replace(";", ",").split(","):
        address = candidate.strip()
        if not address:
            continue
        (valid if EMAIL_PATTERN.match(address) else invalid).append(address)

    # Preserve order, drop duplicates.
    return list(dict.fromkeys(valid)), invalid


def configured_recipients() -> Recipients:
    """Who reports go to, from the environment. Never from a run."""
    settings = get_settings()
    to, bad_to = parse_addresses(settings.report_to)
    cc, bad_cc = parse_addresses(settings.report_cc)

    # An address on both lines is a TO; sending it twice would be noise.
    cc = [address for address in cc if address not in to]

    # Not logged here: this is called several times per send (validation, then
    # the send itself), and warning each time turns one typo into log noise.
    # `send_email` reports it once, where it matters.
    return Recipients(to=to, cc=cc, invalid=bad_to + bad_cc)


def is_configured() -> bool:
    settings = get_settings()
    return bool(settings.sendgrid_api_key and settings.report_from_email)


def configuration_problem() -> str | None:
    """Why email cannot be sent, phrased for the UI. None when it can."""
    settings = get_settings()

    if not settings.sendgrid_api_key:
        return "SENDGRID_API_KEY is not set — see TODO.md."
    if not settings.report_from_email:
        return "REPORT_FROM_EMAIL is not set. It must be a verified SendGrid sender."

    recipients = configured_recipients()
    if not recipients.deliverable:
        return "REPORT_TO is empty, so there is nobody to send the report to."
    return None


async def send_email(*, subject: str, html: str) -> tuple[bool, str | None]:
    """Send one HTML email to the configured recipients.

    Returns `(sent, error)`. Never raises: a delivery failure is recorded
    against the notification row and surfaced in the UI, and must not take down
    the run that produced the report.
    """
    problem = configuration_problem()
    if problem:
        return False, problem

    settings = get_settings()
    recipients = configured_recipients()

    if recipients.invalid:
        log.warning(
            "email.invalid_recipients",
            count=len(recipients.invalid),
            detail="Skipped; check REPORT_TO / REPORT_CC for typos.",
        )

    personalization: dict[str, object] = {"to": [{"email": a} for a in recipients.to]}
    if recipients.cc:
        personalization["cc"] = [{"email": a} for a in recipients.cc]

    payload = {
        "personalizations": [personalization],
        "from": {
            "email": settings.report_from_email,
            "name": settings.report_from_name or "Batanat Harness",
        },
        "subject": subject,
        "content": [{"type": "text/html", "value": html}],
    }
    if settings.report_reply_to:
        payload["reply_to"] = {"email": settings.report_reply_to}

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                SENDGRID_ENDPOINT,
                headers={"Authorization": f"Bearer {settings.sendgrid_api_key}"},
                json=payload,
            )
    except Exception as exc:  # noqa: BLE001
        log.error("email.send_failed", error_type=type(exc).__name__)
        return False, f"{type(exc).__name__}: {exc}"

    # SendGrid accepts with 202, not 200.
    if response.status_code != 202:
        detail = response.text[:200] or f"HTTP {response.status_code}"
        log.error("email.rejected", status_code=response.status_code)
        # 403 here is nearly always an unverified sender, which is worth saying
        # outright rather than leaving someone to read SendGrid's response body.
        if response.status_code == 403:
            detail = (
                f"SendGrid refused the sender {settings.report_from_email!r}. Verify it under "
                "Sender Authentication, or use an address on a domain you have authenticated."
            )
        return False, detail

    log.info(
        "email.sent",
        recipients=len(recipients.to),
        cc=len(recipients.cc),
        subject=subject[:80],
    )
    return True, None
