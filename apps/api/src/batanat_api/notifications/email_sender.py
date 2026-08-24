"""Outbound email, via SendGrid.

Not via Gmail: that connection is `gmail.readonly` by design, so a leaked
SendGrid key can send mail but cannot read Martin's inbox.

Recipients come from the user's row and nowhere else — no env fallback. An
agent that could choose its own recipients could exfiltrate, so the only write
path is the session-authed settings endpoint. The sender stays server config.
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
    """Split a comma-separated list into (valid, invalid).

    Separated rather than rejected so one typo does not stop the report
    reaching everyone else; the bad address is named in the delivery record.
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


def configured_recipients(to_raw: str | None, cc_raw: str | None = None) -> Recipients:
    """Who reports go to, from the user's saved setting. Empty means empty."""
    to, bad_to = parse_addresses(to_raw)
    cc, bad_cc = parse_addresses(cc_raw)

    # An address on both lines is a TO; sending it twice would be noise.
    cc = [address for address in cc if address not in to]

    # Invalid addresses are not logged here — this runs twice per send, and
    # `send_email` reports them once.
    return Recipients(to=to, cc=cc, invalid=bad_to + bad_cc)


def is_configured() -> bool:
    settings = get_settings()
    return bool(settings.sendgrid_api_key and settings.report_from_email)


def configuration_problem(to_raw: str | None, cc_raw: str | None = None) -> str | None:
    """Why email cannot be sent, phrased for the UI. None when it can."""
    settings = get_settings()

    if not settings.sendgrid_api_key:
        return "SENDGRID_API_KEY is not set — see TODO.md."
    if not settings.report_from_email:
        return "REPORT_FROM_EMAIL is not set. It must be a verified SendGrid sender."

    recipients = configured_recipients(to_raw, cc_raw)
    if not recipients.deliverable:
        return "No report recipients are set. Add one in Settings → Report recipients."
    return None


async def send_email(
    *,
    subject: str,
    html: str,
    to_raw: str | None,
    cc_raw: str | None = None,
) -> tuple[bool, str | None]:
    """Send one HTML email. Returns `(sent, error)` and never raises — a
    delivery failure must not take down the run that produced the report."""
    problem = configuration_problem(to_raw, cc_raw)
    if problem:
        return False, problem

    settings = get_settings()
    recipients = configured_recipients(to_raw, cc_raw)

    if recipients.invalid:
        log.warning(
            "email.invalid_recipients",
            count=len(recipients.invalid),
            detail="Skipped; check the report recipient list for typos.",
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
        # 403 is nearly always an unverified sender, and SendGrid's body does
        # not say so.
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
