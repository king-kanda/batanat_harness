"""Skill.MD: versioning and validation.

Skill.MD is procedural memory and sits in the system-prompt position, so it is
the one piece of user-editable text that is read as instruction. That makes the
Rules editor a security surface, and it is handled two ways.

**Structurally**: every security rule lives in code. Tool binding is decided by
`capabilities`, approvals by `approvals.service`. Nothing written in Skill.MD
can widen what a run may do, because nothing reads Skill.MD to make that
decision. This is the real defence.

**Then, belt and braces**: a validator that rejects text trying to redefine tool
behaviour or bypass approval. It is a heuristic and it will have false
positives — which is why it is *not* what the security rests on. It exists to
catch a confused edit early, with a message explaining why.

Versions are immutable. Editing writes a new row and flips `is_active`, so every
run traces to the exact text that was live.
"""

from __future__ import annotations

import hashlib
import re
import uuid
from dataclasses import dataclass, field

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from batanat_api.core.logging import get_logger
from batanat_api.db.models import SkillVersion

log = get_logger(__name__)

MAX_LENGTH = 20_000

#: Phrases that indicate an attempt to change what the system may do, rather
#: than what counts as relevant. Each carries an explanation.
SUSPICIOUS_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (
        re.compile(r"\b(skip|bypass|ignore|without|no need for)\b[^.\n]{0,40}\bapproval", re.I),
        "Approval cannot be bypassed from here. Every CRM write goes through the queue.",
    ),
    (
        re.compile(r"\b(commit_crm_write|approve_pending|crm_delete)\b", re.I),
        "Tool availability is decided by the trigger, not by this document.",
    ),
    (
        re.compile(r"\byou (may|can|should) (now )?(write|delete|modify) [^.\n]{0,30}\bcrm", re.I),
        "This document sets criteria, not capabilities.",
    ),
    (
        re.compile(
            r"\bignore\b[^.\n]{0,30}\b(previous|above|prior)\b[^.\n]{0,20}instruction", re.I
        ),
        "Instruction-override phrasing is not accepted here.",
    ),
    (
        re.compile(r"\b(disregard|override)\b[^.\n]{0,30}\b(system|security|rule|guardrail)", re.I),
        "Security rules are in code and cannot be overridden by this document.",
    ),
    (
        re.compile(r"\bauto[- ]?approve\b", re.I),
        "Automatic approval is not available; a human decides every write.",
    ),
)


@dataclass
class SkillValidation:
    ok: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def validate_skill_content(content: str) -> SkillValidation:
    result = SkillValidation(ok=True)

    if not content or not content.strip():
        result.ok = False
        result.errors.append("The rules cannot be empty.")
        return result

    if len(content) > MAX_LENGTH:
        result.ok = False
        result.errors.append(
            f"Too long: {len(content)} characters, limit {MAX_LENGTH}. This text is sent "
            "with every run, so length is a running cost."
        )

    for pattern, explanation in SUSPICIOUS_PATTERNS:
        match = pattern.search(content)
        if match:
            result.ok = False
            result.errors.append(f"{explanation} (found: {match.group(0)[:60]!r})")

    if len(content) > MAX_LENGTH * 0.7:
        result.warnings.append("This is getting long; consider trimming to keep runs cheap.")
    if "opportunity" not in content.lower():
        result.warnings.append(
            "Nothing here describes what counts as an opportunity — email classification "
            "will be guesswork."
        )

    return result


def checksum(content: str) -> str:
    return hashlib.sha256(content.encode()).hexdigest()


async def get_active(session: AsyncSession, user_id: uuid.UUID) -> SkillVersion | None:
    return (
        await session.execute(
            select(SkillVersion).where(
                SkillVersion.user_id == user_id, SkillVersion.is_active.is_(True)
            )
        )
    ).scalar_one_or_none()


async def list_versions(session: AsyncSession, user_id: uuid.UUID) -> list[SkillVersion]:
    return list(
        (
            await session.execute(
                select(SkillVersion)
                .where(SkillVersion.user_id == user_id)
                .order_by(SkillVersion.version.desc())
            )
        )
        .scalars()
        .all()
    )


async def publish(
    session: AsyncSession,
    user_id: uuid.UUID,
    content: str,
    *,
    created_by: str = "web",
    notes: str | None = None,
) -> SkillVersion:
    """Write a new version and make it active. Never edits an existing row."""
    validation = validate_skill_content(content)
    if not validation.ok:
        raise ValueError("; ".join(validation.errors))

    highest = (
        await session.execute(
            select(SkillVersion.version)
            .where(SkillVersion.user_id == user_id)
            .order_by(SkillVersion.version.desc())
            .limit(1)
        )
    ).scalar_one_or_none()

    # Deactivate first: a partial unique index allows only one active version.
    await session.execute(
        update(SkillVersion)
        .where(SkillVersion.user_id == user_id, SkillVersion.is_active.is_(True))
        .values(is_active=False)
    )
    await session.flush()

    version = SkillVersion(
        user_id=user_id,
        version=(highest or 0) + 1,
        content=content,
        checksum=checksum(content),
        is_active=True,
        created_by=created_by,
        notes=notes,
    )
    session.add(version)
    await session.flush()

    log.info("skill.published", version=version.version, user_id=str(user_id))
    return version


async def rollback_to(
    session: AsyncSession, user_id: uuid.UUID, version_number: int
) -> SkillVersion:
    """Roll back by publishing the old text as a new version.

    Reactivating the old row in place would leave runs pointing at a version
    whose active period is no longer contiguous, and the Activity screen would
    lie about what was live when.
    """
    target = (
        await session.execute(
            select(SkillVersion).where(
                SkillVersion.user_id == user_id, SkillVersion.version == version_number
            )
        )
    ).scalar_one_or_none()
    if target is None:
        raise ValueError(f"No version {version_number}.")

    return await publish(
        session,
        user_id,
        target.content,
        created_by="rollback",
        notes=f"Rolled back to version {version_number}.",
    )


def diff_versions(old: str, new: str) -> list[dict[str, str]]:
    """Line diff for the Rules screen."""
    import difflib

    return [
        {
            "type": (
                "added"
                if line.startswith("+")
                else "removed"
                if line.startswith("-")
                else "context"
            ),
            "text": line[1:] if line[:1] in "+- " else line,
        }
        for line in difflib.unified_diff(old.splitlines(), new.splitlines(), lineterm="", n=2)
        if not line.startswith(("---", "+++", "@@"))
    ]
