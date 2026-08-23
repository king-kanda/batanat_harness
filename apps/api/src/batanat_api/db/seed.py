"""Seed the database with the demo user, tender sources and a starting Skill.MD.

Idempotent: running it twice changes nothing. Run with

    make seed
"""

from __future__ import annotations

import asyncio
import hashlib

from sqlalchemy import select

from batanat_api.config import get_settings
from batanat_api.core.logging import configure_logging, get_logger
from batanat_api.db import enums
from batanat_api.db.models import SkillVersion, TenderSourceRow, User
from batanat_api.db.mongo import ensure_indexes
from batanat_api.db.session import session_scope
from batanat_api.security.passwords import hash_password, verify_password

log = get_logger(__name__)

DEMO_EMAIL = get_settings().default_user_email
DEMO_NAME = "Martin"


# The five sources named in the PRD. `adapter` is resolved to a class in phase 4.
def _shipped_sources() -> list[dict]:
    """Seed rows built from the scraper's own config, so the two cannot drift."""
    from batanat_api.tenders.sources import CONFIGS

    rows = [
        {
            "key": config.key,
            "name": config.name,
            "entity": config.entity,
            "base_url": config.listing_url,
            "listing_url": config.listing_url,
            "fallback_urls": list(config.fallback_urls),
            "adapter": "TableTenderSource",
        }
        for config in CONFIGS
    ]
    rows.append(
        {
            "key": "websearch",
            "name": "Web search fallback (Tavily)",
            "entity": "various",
            "base_url": "https://tavily.com",
            "listing_url": None,
            "fallback_urls": [],
            "adapter": "WebSearchSource",
        }
    )
    return rows


TENDER_SOURCES = _shipped_sources()

# Deliberately criteria-only. Every security rule lives in code, so nothing
# written here — or typed into the Rules editor later — can widen the agent's
# capabilities. See TODO.md: this is placeholder text until the client supplies
# the real thing.
DEFAULT_SKILL_MD = """\
# Batanat — Operating Criteria

## What we do
Batanat works in Kenya's energy sector: solar PV, transmission and distribution
infrastructure, metering, and related EPC and consultancy work.

## What counts as an opportunity in an email
Treat a message as an **opportunity** when it involves any of:
- an invitation to tender, quote, or express interest
- a request for a proposal, pricing, or capability statement
- a prospective client describing a project or requirement
- a partner or supplier raising a specific, live piece of work

Treat as **client** when it concerns an engagement already under way, as
**supplier** when it is inbound from a vendor, and as **administrative** for
invoices, statements, and scheduling.

## When one message is not enough
If a message is a reply with little context, or refers to a deadline or document
discussed earlier, read the whole thread before classifying it. A tender
invitation is often the fourth message in a chain.

## Priority
- **high** — a deadline within 14 days, a named procuring entity, or a direct
  request addressed to Martin. These interrupt: they fire a WhatsApp alert.
- **medium** — relevant but no immediate deadline. Rolls into the next digest.
- **low** — background awareness only.

## What counts as a relevant tender
Relevant when the scope touches solar, transmission, distribution, metering,
electrification, energy audit, or EPC works — and the closing date has not
passed. Prefer KPLC, KenGen, KETRACO, REREC and county energy departments.

Not relevant: supply of unrelated goods, general construction with no energy
component, and anything already known to be closed.

## Tone for notifications
Short and factual. Lead with the deadline and the procuring entity. Never
speculate about value if the source does not state one.
"""


async def seed() -> None:
    async with session_scope() as session:
        user = (
            (await session.execute(select(User).where(User.email == DEMO_EMAIL))).scalars().first()
        )

        if user is None:
            user = User(email=DEMO_EMAIL, name=DEMO_NAME, timezone="Africa/Nairobi")
            session.add(user)
            await session.flush()
            log.info("seed.user.created", email=DEMO_EMAIL, user_id=str(user.id))
        else:
            log.info("seed.user.exists", email=DEMO_EMAIL, user_id=str(user.id))

        # Give the account a password if it has none. Never overwrite one that
        # exists — re-seeding must not silently reset a changed password back to
        # the development default.
        settings = get_settings()
        if user.password_hash is None:
            user.password_hash = hash_password(settings.default_user_password)
            # Recorded, not derived. `/api/auth/me` reads this flag; working it
            # out by hashing the default would cost 0.6s on every page load.
            user.must_change_password = True
            await session.flush()
            log.warning(
                "seed.password.set",
                email=user.email,
                detail="Development default. Change it before this leaves your machine.",
            )
        elif not user.must_change_password and verify_password(
            settings.default_user_password, user.password_hash
        ):
            # An account seeded before the flag existed. One hash here, at seed
            # time, so the warning banner is right without paying for it on
            # every request.
            user.must_change_password = True
            await session.flush()
            log.warning("seed.password.still_default", email=user.email)

        existing_keys = set((await session.execute(select(TenderSourceRow.key))).scalars().all())
        for source in TENDER_SOURCES:
            if source["key"] in existing_keys:
                continue
            session.add(TenderSourceRow(**source, health=enums.SourceHealth.ok))
            log.info("seed.source.created", key=source["key"])

        active_skill = (
            (
                await session.execute(
                    select(SkillVersion).where(
                        SkillVersion.user_id == user.id, SkillVersion.is_active.is_(True)
                    )
                )
            )
            .scalars()
            .first()
        )

        if active_skill is None:
            session.add(
                SkillVersion(
                    user_id=user.id,
                    version=1,
                    content=DEFAULT_SKILL_MD,
                    checksum=hashlib.sha256(DEFAULT_SKILL_MD.encode()).hexdigest(),
                    is_active=True,
                    created_by="seed",
                    notes="Placeholder criteria — replace with the client's own.",
                )
            )
            log.info("seed.skill.created", version=1)

    await ensure_indexes()

    settings = get_settings()
    print(
        f"\nSign in at {settings.web_public_url}/login\n"
        f"  email    {settings.default_user_email}\n"
        f"  password {settings.default_user_password}\n"
    )


def main() -> None:
    configure_logging("info")
    asyncio.run(seed())


if __name__ == "__main__":
    main()
