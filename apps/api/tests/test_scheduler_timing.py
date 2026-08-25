"""When the cron jobs actually fire.

APScheduler numbers day-of-week from Monday=0; crontab numbers it from
Sunday=0, and `CronTrigger.from_crontab` passes the field straight through
without remapping. So "0 8 * * 1" is Tuesday here, not Monday — a silent
off-by-one that nothing else in the system would have caught, because the job
still runs, just on the wrong day.

The fix is weekday names, which mean the same thing under both conventions.
These tests pin that down.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from apscheduler.triggers.cron import CronTrigger

from batanat_api.config import Settings, get_settings

TZ = "Africa/Nairobi"


def _fire_times(expr: str, count: int, *, after: datetime) -> list[datetime]:
    trigger = CronTrigger.from_crontab(expr, timezone=TZ)
    times: list[datetime] = []
    cursor = after
    for _ in range(count):
        nxt = trigger.get_next_fire_time(None, cursor)
        times.append(nxt)
        cursor = nxt + timedelta(seconds=1)
    return times


@pytest.fixture
def sunday_midnight() -> datetime:
    # 2026-08-23 is a Sunday. Starting here means a Monday expression must fire
    # tomorrow, and a Tuesday one the day after — the two are distinguishable.
    return datetime(2026, 8, 23, 0, 0, tzinfo=ZoneInfo(TZ))


def test_numeric_day_of_week_is_off_by_one(sunday_midnight) -> None:
    """The trap, asserted directly so the reason for using names is on record."""
    assert _fire_times("0 8 * * 1", 1, after=sunday_midnight)[0].strftime("%a") == "Tue"
    assert _fire_times("0 8 * * mon", 1, after=sunday_midnight)[0].strftime("%a") == "Mon"


def test_the_weekly_digest_lands_on_monday_morning(sunday_midnight) -> None:
    settings = get_settings()
    fires = _fire_times(settings.tender_cron_weekly, 3, after=sunday_midnight)

    assert [f.strftime("%a") for f in fires] == ["Mon", "Mon", "Mon"]
    assert {(f.hour, f.minute) for f in fires} == {(8, 0)}
    # Consecutive weeks, not consecutive days.
    assert (fires[1] - fires[0]).days == 7


def test_the_daily_sweep_runs_three_times_a_day(sunday_midnight) -> None:
    """The *shipped* schedule, read from the field default rather than settings.

    `get_settings()` resolves `.env`, so asserting exact hours against it makes
    this test say "your machine is configured the way mine is" instead of "the
    schedule we ship is the one documented". A developer with a custom
    `TENDER_CRON_DAILY` would fail a test about a value they deliberately
    changed, and CI — which has no `.env` — would pass regardless.
    """
    shipped = Settings.model_fields["tender_cron_daily"].default
    fires = _fire_times(shipped, 6, after=sunday_midnight)

    assert [(f.hour, f.minute) for f in fires] == [
        (11, 0),
        (17, 0),
        (20, 0),
        (11, 0),
        (17, 0),
        (20, 0),
    ]
    assert fires[0].date() == fires[1].date() == fires[2].date()
    assert (fires[3].date() - fires[0].date()).days == 1


def test_maintenance_runs_nightly_outside_working_hours(sunday_midnight) -> None:
    settings = get_settings()
    fires = _fire_times(settings.maintenance_cron, 3, after=sunday_midnight)

    assert {(f.hour, f.minute) for f in fires} == {(2, 0)}
    assert (fires[1] - fires[0]).days == 1


def test_every_configured_expression_parses() -> None:
    """A malformed cron raises at startup, which is a boot failure in production."""
    settings = get_settings()
    for expr in (
        settings.tender_cron_daily,
        settings.tender_cron_weekly,
        settings.maintenance_cron,
    ):
        CronTrigger.from_crontab(expr, timezone=settings.scheduler_timezone)


def test_no_configured_expression_uses_a_numeric_weekday() -> None:
    """Numbers in that field are ambiguous between the two conventions."""
    settings = get_settings()
    for expr in (
        settings.tender_cron_daily,
        settings.tender_cron_weekly,
        settings.maintenance_cron,
    ):
        day_of_week = expr.split()[4]
        assert not any(c.isdigit() for c in day_of_week), (
            f"{expr!r} uses a numeric weekday; use names (mon, tue, …) instead"
        )
