"""The scheduler.

Three schedules, all evaluated in Africa/Nairobi because that is the timezone
the deadlines are in:

* **11:00 and 17:00 daily** — tender sweep, 24-hour lookback.
* **08:00 Monday** — weekly sweep, 72-hour lookback, catching the weekend.
* **02:00 nightly** — maintenance.

Every job takes a Redis lock before doing anything. Two API processes with the
scheduler enabled would otherwise both fire at 11:00, producing two runs, two
reports and two WhatsApp alerts for the same tenders.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from redis.asyncio import from_url

from batanat_api.config import get_settings
from batanat_api.core.logging import get_logger
from batanat_api.core.run_context import run_context
from batanat_api.db.session import session_scope

log = get_logger(__name__)

_scheduler: AsyncIOScheduler | None = None

#: Long enough that a slow job keeps its lock; short enough that a crashed one
#: does not block the next window.
LOCK_TTL_SECONDS = 1800


async def _acquire(job: str) -> bool:
    client = from_url(get_settings().redis_url)
    try:
        return bool(await client.set(f"job:lock:{job}", "1", ex=LOCK_TTL_SECONDS, nx=True))
    except Exception:  # noqa: BLE001
        log.warning("scheduler.lock_unavailable", job=job)
        return True  # Redis down: better a duplicate run than no run
    finally:
        await client.aclose()


async def _release(job: str) -> None:
    client = from_url(get_settings().redis_url)
    try:
        await client.delete(f"job:lock:{job}")
    except Exception:  # noqa: BLE001
        pass
    finally:
        await client.aclose()


async def _for_each_user(fn, job_name: str) -> None:
    from sqlalchemy import select

    from batanat_api.db.models import User

    if not await _acquire(job_name):
        log.info("scheduler.skipped", job=job_name, reason="another process holds the lock")
        return

    try:
        with run_context():
            async with session_scope() as session:
                users = (
                    (await session.execute(select(User).where(User.is_active.is_(True))))
                    .scalars()
                    .all()
                )
                for user in users:
                    try:
                        await fn(session, user.id)
                    except Exception as exc:  # noqa: BLE001
                        log.exception(
                            "scheduler.job_failed",
                            job=job_name,
                            error_type=type(exc).__name__,
                        )
    finally:
        await _release(job_name)


async def tender_sweep(lookback_hours: int = 24, label_prefix: str = "daily") -> None:
    from batanat_api.notifications.dispatcher import dispatch_tender_report
    from batanat_api.triggers.tender_trigger import run_tender_cycle

    async def one(session, user_id: uuid.UUID) -> None:
        now = datetime.now(UTC)
        report = await run_tender_cycle(
            session,
            user_id,
            lookback_hours=lookback_hours,
            label=f"{now.strftime('%Y-%m-%d-%H%M')}",
        )
        await dispatch_tender_report(session, user_id, report)

    await _for_each_user(one, f"tender_sweep:{label_prefix}")


async def nightly_maintenance() -> None:
    from batanat_api.scheduler.maintenance import run_all

    async def one(session, user_id: uuid.UUID) -> None:
        await run_all(session, user_id)

    await _for_each_user(one, "maintenance")


def start_scheduler() -> AsyncIOScheduler:
    """Start the cron jobs. Called from the API lifespan."""
    global _scheduler
    if _scheduler is not None:
        return _scheduler

    settings = get_settings()
    scheduler = AsyncIOScheduler(timezone=settings.scheduler_timezone)

    scheduler.add_job(
        tender_sweep,
        CronTrigger.from_crontab(settings.tender_cron_daily, timezone=settings.scheduler_timezone),
        kwargs={"lookback_hours": 24, "label_prefix": "daily"},
        id="tender_daily",
        replace_existing=True,
        misfire_grace_time=1800,
    )
    scheduler.add_job(
        tender_sweep,
        CronTrigger.from_crontab(settings.tender_cron_weekly, timezone=settings.scheduler_timezone),
        kwargs={"lookback_hours": 72, "label_prefix": "weekly"},
        id="tender_weekly",
        replace_existing=True,
        misfire_grace_time=3600,
    )
    scheduler.add_job(
        nightly_maintenance,
        CronTrigger.from_crontab(settings.maintenance_cron, timezone=settings.scheduler_timezone),
        id="maintenance",
        replace_existing=True,
        misfire_grace_time=3600,
    )

    scheduler.start()
    _scheduler = scheduler
    log.info(
        "scheduler.started",
        timezone=settings.scheduler_timezone,
        jobs=[j.id for j in scheduler.get_jobs()],
    )
    return scheduler


def stop_scheduler() -> None:
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None


def next_run_times() -> list[dict[str, str]]:
    """What the Dashboard shows as 'next scheduled run'."""
    if _scheduler is None:
        return []
    return [
        {
            "id": job.id,
            "next_run_at": job.next_run_time.isoformat() if job.next_run_time else "paused",
        }
        for job in _scheduler.get_jobs()
    ]
