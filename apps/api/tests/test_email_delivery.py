"""Report delivery via SendGrid.

Three things are worth holding in place here. Recipients come from the user's
own saved setting and never from a run — an agent that could choose its own
recipients could exfiltrate. A single typo in the cc list must not stop the
report reaching everyone else, because that failure would be invisible. And an
empty setting must refuse loudly rather than fall back to anything: there is no
environment default any more, on purpose.
"""

from __future__ import annotations

import pytest

from batanat_api.config import get_settings
from batanat_api.notifications import email_sender
from batanat_api.notifications.email_sender import (
    configuration_problem,
    configured_recipients,
    is_configured,
    parse_addresses,
)

MARTIN = "martin@batanat.co.ke"


@pytest.fixture
def configured(monkeypatch: pytest.MonkeyPatch):
    """SendGrid credentials and a verified sender. Recipients are per-call."""
    settings = get_settings()
    monkeypatch.setattr(settings, "sendgrid_api_key", "SG.test-key")
    monkeypatch.setattr(settings, "report_from_email", "reports@batanat.co.ke")
    return settings


# --- parsing what a user typed -----------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("a@x.com", ["a@x.com"]),
        ("a@x.com,b@y.com", ["a@x.com", "b@y.com"]),
        ("a@x.com, b@y.com ", ["a@x.com", "b@y.com"]),
        ("a@x.com;b@y.com", ["a@x.com", "b@y.com"]),
        ("a@x.com,,b@y.com", ["a@x.com", "b@y.com"]),
        ("a@x.com,a@x.com", ["a@x.com"]),
        ("", []),
        (None, []),
    ],
)
def test_address_lists_are_parsed_forgivingly(raw, expected) -> None:
    valid, _ = parse_addresses(raw)
    assert valid == expected


def test_a_malformed_address_is_separated_not_silently_dropped() -> None:
    valid, invalid = parse_addresses("good@x.com, not-an-email, also@y.com")
    assert valid == ["good@x.com", "also@y.com"]
    assert invalid == ["not-an-email"]


def test_one_bad_cc_does_not_block_the_rest() -> None:
    recipients = configured_recipients(MARTIN, "ops@batanat.co.ke, typo-at-example")
    assert recipients.to == [MARTIN]
    assert recipients.cc == ["ops@batanat.co.ke"]
    assert recipients.invalid == ["typo-at-example"]
    assert recipients.deliverable is True


def test_an_address_on_both_lines_is_not_sent_twice() -> None:
    recipients = configured_recipients(MARTIN, f"{MARTIN}, ops@batanat.co.ke")
    assert recipients.to == [MARTIN]
    assert recipients.cc == ["ops@batanat.co.ke"]


# --- there is no environment fallback ----------------------------------------


def test_empty_recipients_mean_empty(configured) -> None:
    """The whole point of dropping the env fallback: nothing is substituted."""
    assert configured_recipients("", "").to == []
    assert configured_recipients(None, None).to == []
    assert configured_recipients("", "").deliverable is False


def test_a_cc_alone_cannot_deliver_a_report() -> None:
    """A cc with no To is not a working configuration, and must not look like one."""
    recipients = configured_recipients("", "someone@batanat.co.ke")
    assert recipients.cc == ["someone@batanat.co.ke"]
    assert recipients.deliverable is False


def test_the_settings_object_no_longer_carries_recipients() -> None:
    """Guards the removal: a stray REPORT_TO in an .env must not resurrect it."""
    settings = get_settings()
    assert not hasattr(settings, "report_to")
    assert not hasattr(settings, "report_cc")


# --- refusing to send, legibly -----------------------------------------------


def test_no_api_key_is_reported_clearly(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "sendgrid_api_key", None)
    assert is_configured() is False
    assert "SENDGRID_API_KEY" in (configuration_problem(MARTIN) or "")


def test_no_sender_is_reported_clearly(monkeypatch: pytest.MonkeyPatch, configured) -> None:
    monkeypatch.setattr(configured, "report_from_email", None)
    assert "REPORT_FROM_EMAIL" in (configuration_problem(MARTIN) or "")


def test_no_recipients_is_reported_clearly(configured) -> None:
    """Silently succeeding with nobody to send to is the worst outcome here."""
    problem = configuration_problem("", "")
    assert problem is not None
    # Points at the one place it can be fixed, now that there is only one.
    assert "Settings" in problem


def test_a_fully_configured_setup_reports_no_problem(configured) -> None:
    assert configuration_problem(MARTIN) is None
    assert is_configured() is True


async def test_sending_without_configuration_returns_the_reason(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(get_settings(), "sendgrid_api_key", None)
    sent, error = await email_sender.send_email(subject="Report", html="<p>hi</p>", to_raw=MARTIN)
    assert sent is False
    assert "SENDGRID_API_KEY" in (error or "")


# --- the request SendGrid actually receives ----------------------------------


class _FakeResponse:
    def __init__(self, status_code: int, text: str = ""):
        self.status_code = status_code
        self.text = text


def _capture(monkeypatch: pytest.MonkeyPatch, response: _FakeResponse) -> dict:
    captured: dict = {}

    class _Client:
        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def post(self, url, headers=None, json=None):
            captured["url"] = url
            captured["headers"] = headers
            captured["json"] = json
            return response

    monkeypatch.setattr(email_sender.httpx, "AsyncClient", _Client)
    return captured


async def test_a_successful_send_builds_the_expected_payload(
    monkeypatch: pytest.MonkeyPatch, configured
) -> None:
    captured = _capture(monkeypatch, _FakeResponse(202))

    sent, error = await email_sender.send_email(
        subject="Tender report",
        html="<p>x</p>",
        to_raw=MARTIN,
        cc_raw="ops@batanat.co.ke",
    )

    assert (sent, error) == (True, None)
    body = captured["json"]
    assert body["personalizations"][0]["to"] == [{"email": MARTIN}]
    assert body["personalizations"][0]["cc"] == [{"email": "ops@batanat.co.ke"}]
    assert body["from"]["email"] == "reports@batanat.co.ke"
    assert body["subject"] == "Tender report"
    assert body["content"][0]["type"] == "text/html"
    assert captured["headers"]["Authorization"] == "Bearer SG.test-key"


async def test_the_sender_is_never_taken_from_the_recipient_setting(
    monkeypatch: pytest.MonkeyPatch, configured
) -> None:
    """A user picks destinations, not identity."""
    captured = _capture(monkeypatch, _FakeResponse(202))
    await email_sender.send_email(subject="s", html="<p>x</p>", to_raw="someone-else@evil.com")
    assert captured["json"]["from"]["email"] == "reports@batanat.co.ke"


async def test_no_cc_key_is_sent_when_there_is_no_cc(
    monkeypatch: pytest.MonkeyPatch, configured
) -> None:
    captured = _capture(monkeypatch, _FakeResponse(202))
    await email_sender.send_email(subject="s", html="<p>x</p>", to_raw=MARTIN)
    assert "cc" not in captured["json"]["personalizations"][0]


async def test_202_is_the_success_code_not_200(monkeypatch: pytest.MonkeyPatch, configured) -> None:
    """SendGrid accepts with 202. Treating only 200 as success would report
    every successful send as a failure."""
    _capture(monkeypatch, _FakeResponse(202))
    sent, _ = await email_sender.send_email(subject="s", html="<p>x</p>", to_raw=MARTIN)
    assert sent is True


async def test_an_unverified_sender_gets_an_actionable_message(
    monkeypatch: pytest.MonkeyPatch, configured
) -> None:
    """403 from SendGrid is almost always this, and the raw body does not say so."""
    _capture(monkeypatch, _FakeResponse(403, '{"errors":[{"message":"forbidden"}]}'))
    sent, error = await email_sender.send_email(subject="s", html="<p>x</p>", to_raw=MARTIN)

    assert sent is False
    assert "Sender Authentication" in (error or "")
    assert "reports@batanat.co.ke" in (error or "")


async def test_a_network_failure_is_returned_not_raised(
    monkeypatch: pytest.MonkeyPatch, configured
) -> None:
    """A delivery failure must not take down the run that produced the report."""

    class _Exploding:
        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def post(self, *args, **kwargs):
            raise ConnectionError("network down")

    monkeypatch.setattr(email_sender.httpx, "AsyncClient", _Exploding)
    sent, error = await email_sender.send_email(subject="s", html="<p>x</p>", to_raw=MARTIN)

    assert sent is False
    assert "ConnectionError" in (error or "")


def test_recipients_are_described_for_the_delivery_record() -> None:
    assert MARTIN in configured_recipients(MARTIN).describe()


# --- the dispatcher reads the recipients off the user ------------------------


async def test_the_dispatcher_sends_to_the_users_own_addresses(
    monkeypatch: pytest.MonkeyPatch, configured, session, user
) -> None:
    from batanat_api.notifications import dispatcher

    user.report_to = "director@batanat.co.ke"
    user.report_cc = "board@batanat.co.ke"
    await session.commit()

    captured = _capture(monkeypatch, _FakeResponse(202))
    sent, error = await dispatcher.send_email(
        user_id=user.id, subject="s", html="<p>x</p>", session=session
    )

    assert (sent, error) == (True, None)
    personalization = captured["json"]["personalizations"][0]
    assert personalization["to"] == [{"email": "director@batanat.co.ke"}]
    assert personalization["cc"] == [{"email": "board@batanat.co.ke"}]


async def test_a_user_with_no_recipients_gets_a_refusal_not_a_default(
    monkeypatch: pytest.MonkeyPatch, configured, session, user
) -> None:
    """No env fallback means this must fail, and say why."""
    from batanat_api.notifications import dispatcher

    assert user.report_to == ""

    _capture(monkeypatch, _FakeResponse(202))
    sent, error = await dispatcher.send_email(
        user_id=user.id, subject="s", html="<p>x</p>", session=session
    )

    assert sent is False
    assert "Settings" in (error or "")


async def test_a_missing_user_does_not_fall_back_to_anyone(
    monkeypatch: pytest.MonkeyPatch, configured, session
) -> None:
    """A run that outlives its account must not mail whoever is left in config."""
    import uuid as _uuid

    from batanat_api.notifications import dispatcher

    _capture(monkeypatch, _FakeResponse(202))
    sent, error = await dispatcher.send_email(
        user_id=_uuid.uuid4(), subject="s", html="<p>x</p>", session=session
    )

    assert sent is False
    assert "No such user" in (error or "")
