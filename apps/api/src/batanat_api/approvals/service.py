"""The approval queue.

Nothing reaches Zoho except through here, and execution is **direct** — no
model, no tools, no loop. The payload was reviewed by a human; re-running an
agent over it would mean the thing executed is not the thing approved.

State machine, and every transition is one-way:

    pending ──approve──> approved ──execute──> executed
       │                     │                    └─ failed
       ├──reject───> rejected
       └──expire (48h)──> expired

`execute_approval` refuses anything not in `approved`. That is what stops
`commit_crm_write` from being used to originate a write: the only way into
`approved` is a human decision.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from batanat_api.config import get_settings
from batanat_api.core.logging import get_logger
from batanat_api.crm.client import ZohoClient
from batanat_api.db import enums
from batanat_api.db.models import Approval

log = get_logger(__name__)


class ApprovalError(RuntimeError):
    pass


class ApprovalNotFoundError(ApprovalError):
    pass


class ApprovalStateError(ApprovalError):
    """The approval is not in a state where this action makes sense."""


async def get_approval(
    session: AsyncSession, approval_id: uuid.UUID, *, user_id: uuid.UUID
) -> Approval:
    approval = (
        await session.execute(
            select(Approval).where(Approval.id == approval_id, Approval.user_id == user_id)
        )
    ).scalar_one_or_none()
    if approval is None:
        raise ApprovalNotFoundError(f"No approval {approval_id}.")
    return approval


async def list_pending(session: AsyncSession, user_id: uuid.UUID) -> list[Approval]:
    return list(
        (
            await session.execute(
                select(Approval)
                .where(
                    Approval.user_id == user_id,
                    Approval.status == enums.ApprovalStatus.pending,
                )
                .order_by(Approval.created_at.asc())
            )
        )
        .scalars()
        .all()
    )


async def decide_approval(
    session: AsyncSession,
    approval_id: uuid.UUID,
    *,
    user_id: uuid.UUID,
    approve: bool,
    actor: str,
    reason: str | None = None,
    edited_payload: dict[str, Any] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Record a human decision, and execute immediately if approved.

    `edited_payload` supports edit-then-approve: what gets executed is what the
    human left on screen, not what the agent proposed.
    """
    now = now or datetime.now(UTC)
    approval = await get_approval(session, approval_id, user_id=user_id)

    if approval.status is not enums.ApprovalStatus.pending:
        raise ApprovalStateError(
            f"Approval {approval_id} is already {approval.status.value}; it cannot be "
            "decided again."
        )
    if approval.expires_at <= now:
        approval.status = enums.ApprovalStatus.expired
        await session.flush()
        raise ApprovalStateError("This approval expired before it was decided.")

    if not approve:
        approval.status = enums.ApprovalStatus.rejected
        approval.approved_by = actor
        approval.approved_at = now
        approval.execution_result = {"rejected_reason": reason}
        await session.flush()
        log.info("approval.rejected", approval_id=str(approval_id), actor=actor)
        return {"approval_id": str(approval_id), "status": "rejected"}

    if edited_payload is not None:
        from batanat_api.crm.client import filter_payload

        kept, dropped = filter_payload(approval.module, edited_payload)
        if not kept:
            raise ApprovalError("The edited payload has no writable fields.")
        approval.proposed_payload = kept
        if dropped:
            log.warning("approval.edited_fields_dropped", dropped=dropped)

    approval.status = enums.ApprovalStatus.approved
    approval.approved_by = actor
    approval.approved_at = now
    await session.flush()
    log.info("approval.approved", approval_id=str(approval_id), actor=actor)

    return await execute_approval(session, approval_id, user_id=user_id, now=now)


async def execute_approval(
    session: AsyncSession,
    approval_id: uuid.UUID,
    *,
    user_id: uuid.UUID,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Perform the approved write. Direct execution — no LLM involved."""
    now = now or datetime.now(UTC)
    settings = get_settings()
    approval = await get_approval(session, approval_id, user_id=user_id)

    if approval.status is enums.ApprovalStatus.executed:
        # Idempotent: a retried callback must not write twice.
        return {
            "approval_id": str(approval_id),
            "status": "executed",
            "result": approval.execution_result,
            "note": "Already executed; not repeated.",
        }

    if approval.status is not enums.ApprovalStatus.approved:
        raise ApprovalStateError(
            f"Approval {approval_id} is {approval.status.value}, not approved. Only a human "
            "decision can move it to approved."
        )

    if settings.crm_dry_run:
        approval.status = enums.ApprovalStatus.executed
        approval.executed_at = now
        approval.execution_result = {"dry_run": True, "payload": approval.proposed_payload}
        await session.flush()
        log.warning("approval.dry_run", approval_id=str(approval_id), module=approval.module)
        return {
            "approval_id": str(approval_id),
            "status": "executed",
            "dry_run": True,
            "note": "CRM_DRY_RUN is on: the write was logged, not sent to Zoho.",
        }

    client = ZohoClient(session, user_id)
    try:
        if approval.operation == "update" and approval.record_id:
            result = await client.update(
                approval.module, approval.record_id, approval.proposed_payload
            )
        else:
            result = await client.create(approval.module, approval.proposed_payload)
    except Exception as exc:  # noqa: BLE001
        approval.status = enums.ApprovalStatus.failed
        approval.executed_at = now
        approval.execution_result = {"error": f"{type(exc).__name__}: {exc}"}
        await session.flush()
        log.error(
            "approval.execution_failed", approval_id=str(approval_id), error_type=type(exc).__name__
        )
        raise

    approval.status = enums.ApprovalStatus.executed
    approval.executed_at = now
    approval.execution_result = result
    await session.flush()

    log.info("approval.executed", approval_id=str(approval_id), module=approval.module)
    return {
        "approval_id": str(approval_id),
        "status": "executed",
        "module": approval.module,
        "result": result,
    }


async def expire_stale(session: AsyncSession, *, now: datetime | None = None) -> int:
    """Auto-reject approvals past their 48-hour window. Run by the nightly job."""
    now = now or datetime.now(UTC)
    result = await session.execute(
        update(Approval)
        .where(
            Approval.status == enums.ApprovalStatus.pending,
            Approval.expires_at <= now,
        )
        .values(status=enums.ApprovalStatus.expired)
        .returning(Approval.id)
    )
    expired = list(result.scalars().all())
    if expired:
        log.info("approvals.expired", count=len(expired))
    return len(expired)


# --- WhatsApp reply parsing --------------------------------------------------


def parse_decision_reply(body: str) -> tuple[str, int] | None:
    """Parse `APPROVE 3` / `REJECT 2` from a WhatsApp message.

    Returns (decision, index) where index is the 1-based position in the
    numbered list that was sent. Anything else returns None — WhatsApp cannot
    originate a write, only answer a question we asked.
    """
    import re

    match = re.match(r"^\s*(approve|reject|yes|no)\s*(\d+)?\s*$", body or "", re.IGNORECASE)
    if not match:
        return None

    word = match.group(1).lower()
    decision = "approve" if word in {"approve", "yes"} else "reject"
    index = int(match.group(2)) if match.group(2) else 1
    if index < 1:
        return None
    return decision, index
