"""Turning what a site published into something we can store and compare.

Kenyan procurement sites write dates and money every way a human might: "22
July 2026", "22/07/2026", "2026-07-22", "22nd July 2026, 11.00 am". None of
these parse with a single format string, and getting one wrong means a closing
date off by a month.

The rule throughout: **return None rather than guess.** A tender with no closing
date is a tender we report without a closing date. A tender with a closing date
we invented is a missed bid.
"""

from __future__ import annotations

import re
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo

NAIROBI = ZoneInfo("Africa/Nairobi")

# Ordered most-specific first. Day-first throughout: Kenyan sites write
# 07/08/2026 meaning 7 August, never 8 July.
DATE_FORMATS = (
    "%d %B %Y",
    "%d %b %Y",
    "%B %d, %Y",
    "%b %d, %Y",
    "%Y-%m-%d",
    "%d/%m/%Y",
    "%d-%m-%Y",
    "%d.%m.%Y",
    "%d/%m/%y",
)

ORDINAL = re.compile(r"(\d{1,2})(st|nd|rd|th)\b", re.IGNORECASE)
TIME_TAIL = re.compile(
    r"\b(at|by|before)?\s*\d{1,2}[:.]\d{2}\s*(am|pm|hrs|hours|noon|east african time|eat)?\.?$",
    re.IGNORECASE,
)
WHITESPACE = re.compile(r"\s+")

CURRENCY_SYMBOLS = {
    "kes": "KES",
    "ksh": "KES",
    "kshs": "KES",
    "sh": "KES",
    "usd": "USD",
    "us$": "USD",
    "$": "USD",
    "eur": "EUR",
    "€": "EUR",
    "gbp": "GBP",
    "£": "GBP",
}

MONEY = re.compile(
    r"(?P<currency>kshs?|kes|usd|us\$|eur|gbp|[$€£])\s*"
    r"(?P<amount>[\d][\d,\s]*(?:\.\d{1,2})?)"
    r"\s*(?P<scale>million|billion|m|bn)?",
    re.IGNORECASE,
)


def clean_text(value: str | None) -> str | None:
    """Collapse whitespace; empty and placeholder values become None."""
    if value is None:
        return None
    text = WHITESPACE.sub(" ", value).strip().strip("|").strip()
    if text in {"", "-", "—", "–", "N/A", "n/a", "NA", "TBA", "TBD", "..."}:
        return None
    return text


def parse_date(value: str | None, *, now: datetime | None = None) -> datetime | None:
    """Parse a published date. Returns an aware UTC datetime, or None."""
    text = clean_text(value)
    if not text:
        return None

    text = ORDINAL.sub(r"\1", text)
    text = TIME_TAIL.sub("", text).strip().rstrip(",").strip()
    # Drop a leading weekday: "Monday, 22 July 2026".
    text = re.sub(r"^[A-Za-z]+day,?\s+", "", text)

    for fmt in DATE_FORMATS:
        try:
            parsed = datetime.strptime(text, fmt)
        except ValueError:
            continue
        # Sites publish local dates; store them as the Nairobi day they meant.
        return parsed.replace(tzinfo=NAIROBI).astimezone(UTC)

    return None


def parse_money(value: str | None) -> tuple[Decimal | None, str | None]:
    """Extract an amount and its currency. Both None unless both are certain.

    An amount with no stated currency is useless — and worse, misleading — so it
    is discarded rather than assumed to be shillings.
    """
    text = clean_text(value)
    if not text:
        return None, None

    match = MONEY.search(text)
    if not match:
        return None, None

    currency = CURRENCY_SYMBOLS.get(match.group("currency").lower().rstrip("."))
    if not currency:
        return None, None

    raw = match.group("amount").replace(",", "").replace(" ", "")
    try:
        amount = Decimal(raw)
    except (InvalidOperation, ValueError):
        return None, None

    scale = (match.group("scale") or "").lower()
    if scale in {"million", "m"}:
        amount *= 1_000_000
    elif scale in {"billion", "bn"}:
        amount *= 1_000_000_000

    return amount, currency


def is_closed(closing: datetime | None, *, now: datetime | None = None) -> bool:
    """Has the deadline passed? Unknown deadlines are not treated as closed."""
    if closing is None:
        return False
    return closing < (now or datetime.now(UTC))


def looks_like_reference(value: str | None) -> bool:
    """Reference numbers carry digits. 'Download' and 'Open' do not."""
    text = clean_text(value)
    if not text or len(text) < 3 or len(text) > 200:
        return False
    return any(char.isdigit() for char in text)


def to_nairobi_date(value: datetime | None) -> date | None:
    return value.astimezone(NAIROBI).date() if value else None
