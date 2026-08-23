"""The real tool handlers.

Each one is a thin adapter: validate, call the client, archive the raw response,
return something small enough for the model to read. The interesting rules —
which tools a run may see, what may be written — live in `capabilities` and
`crm.client`, not here.

`propose_crm_entry` is the one to read closely. It never touches Zoho. It
validates, diffs against current state, and writes an `approvals` row. That is
the whole of invariant 3.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert

from batanat_api.agent.tools.registry import ToolContext, ToolSpec, register
from batanat_api.core.logging import get_logger
from batanat_api.crm.client import (
    WRITABLE_MODULES,
    ModuleNotAllowedError,
    ZohoClient,
    compute_diff,
    filter_payload,
)
from batanat_api.db import enums
from batanat_api.db.models import Approval, Email, Tender
from batanat_api.db.mongo import RAW_EMAILS, RAW_TOOL_RESPONSES, archive
from batanat_api.gmail.cleaning import clean_body
from batanat_api.gmail.client import GmailClient
from batanat_api.tenders.base import PoliteClient
from batanat_api.tenders.ingest import ingest_report, record_source_health
from batanat_api.tenders.search_source import WebSearchSource
from batanat_api.tenders.sources import build_sources

log = get_logger(__name__)

#: Approvals expire after this long, then auto-reject. From the PRD.
APPROVAL_TTL = timedelta(hours=48)
#: How many approvals one run may create. Stops a confused loop queueing 200.
MAX_PROPOSALS_PER_RUN = 10

from pydantic import BaseModel, Field  # noqa: E402

# --- email -------------------------------------------------------------------


class ReadEmailsArgs(BaseModel):
    since: str | None = Field(default=None, description="Gmail query date, e.g. 2026/08/20.")
    limit: int = Field(default=20, ge=1, le=50)


async def read_emails(context: ToolContext, args: ReadEmailsArgs) -> dict[str, Any]:
    client = GmailClient(context.session, context.user_id)
    query = f"after:{args.since}" if args.since else "newer_than:7d"

    message_ids, _ = await client.list_messages(query=query, limit=args.limit)
    summaries: list[dict[str, Any]] = []

    for message_id in message_ids:
        message = await client.get_message(message_id)
        body, truncated = clean_body(message.body)

        row_id = uuid.uuid4()
        statement = (
            insert(Email)
            .values(
                id=row_id,
                user_id=context.user_id,
                gmail_message_id=message.id,
                gmail_thread_id=message.thread_id,
                history_id=message.history_id,
                from_address=message.from_address,
                from_name=message.from_name,
                subject=message.subject,
                snippet=message.snippet,
                received_at=message.received_at,
                created_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
            )
            # At-least-once delivery and re-syncs mean we see messages twice.
            .on_conflict_do_nothing(index_elements=["user_id", "gmail_message_id"])
            .returning(Email.id)
        )
        result = (await context.session.execute(statement)).scalar_one_or_none()
        stored_id = (
            result
            or (
                await context.session.execute(
                    select(Email.id).where(
                        Email.user_id == context.user_id, Email.gmail_message_id == message.id
                    )
                )
            ).scalar_one()
        )

        await archive(
            RAW_EMAILS,
            stored_id,
            message.raw,
            user_id=str(context.user_id),
            gmail_message_id=message.id,
        )

        summaries.append(
            {
                "email_id": str(stored_id),
                "from": message.from_address,
                "subject": message.subject,
                "received_at": message.received_at.isoformat() if message.received_at else None,
                "body": body,
                "truncated": truncated,
            }
        )

    return {"count": len(summaries), "emails": summaries}


class ReadThreadArgs(BaseModel):
    email_id: str = Field(description="Id of an email returned by read_email.")


async def read_thread(context: ToolContext, args: ReadThreadArgs) -> dict[str, Any]:
    """Read the whole conversation an email belongs to.

    A single message is often not enough to classify: the tender invitation may
    be the fourth reply, and the deadline may have been stated in the first.
    Reading the thread also *reduces* the text involved — each reply re-quotes
    everything above it, so the quoted copies are stripped and the real messages
    used instead.
    """
    from batanat_api.gmail.cleaning import render_thread

    email = (
        await context.session.execute(
            select(Email).where(
                Email.id == uuid.UUID(args.email_id), Email.user_id == context.user_id
            )
        )
    ).scalar_one_or_none()
    if email is None:
        raise ValueError(f"No email {args.email_id} for this user.")
    if not email.gmail_thread_id:
        raise ValueError("That email has no thread id recorded.")

    client = GmailClient(context.session, context.user_id)
    messages = await client.get_thread(email.gmail_thread_id)
    transcript, truncated = render_thread(messages)

    await archive(
        RAW_TOOL_RESPONSES,
        uuid.uuid4(),
        {"thread_id": email.gmail_thread_id, "messages": [m.raw for m in messages]},
        run_id=str(context.run_id),
        tool_name="read_thread",
    )

    return {
        "thread_id": email.gmail_thread_id,
        "subject": email.subject,
        "message_count": len(messages),
        "truncated": truncated,
        "transcript": transcript,
    }


class ClassifyEmailArgs(BaseModel):
    email_id: str = Field(description="Id returned by read_emails.")
    category: str = Field(
        description="opportunity | client | supplier | administrative | spam | not_relevant"
    )
    priority: str = Field(description="high | medium | low")
    confidence: float = Field(ge=0.0, le=1.0)
    reasoning: str = Field(description="Why, in one or two sentences.")
    suggested_action: str | None = None


async def classify_email(context: ToolContext, args: ClassifyEmailArgs) -> dict[str, Any]:
    """Record the model's classification of an email it has already read.

    The scoring is the model's job — it has the Skill.MD criteria in its system
    prompt. This tool's job is to validate the verdict against the enums and
    store it, so an invented category fails here rather than reaching the UI.
    """
    try:
        category = enums.EmailCategory(args.category)
        priority = enums.Priority(args.priority)
    except ValueError as exc:
        raise ValueError(
            f"{exc}. Valid categories: {[c.value for c in enums.EmailCategory]}; "
            f"priorities: {[p.value for p in enums.Priority]}."
        ) from None

    email = (
        await context.session.execute(
            select(Email).where(
                Email.id == uuid.UUID(args.email_id), Email.user_id == context.user_id
            )
        )
    ).scalar_one_or_none()
    if email is None:
        raise ValueError(f"No email {args.email_id} for this user.")

    email.category = category
    email.priority = priority
    email.confidence = args.confidence
    email.classification = {
        "reasoning": args.reasoning,
        "suggested_action": args.suggested_action,
    }
    email.processed_at = datetime.now(UTC)
    email.run_id = context.run_id
    await context.session.flush()

    return {
        "email_id": args.email_id,
        "category": category.value,
        "priority": priority.value,
        "confidence": args.confidence,
    }


# --- tenders -----------------------------------------------------------------


class ScrapeTendersArgs(BaseModel):
    sources: list[str] = Field(default_factory=list, description="Source keys; empty means all.")


async def scrape_tenders(context: ToolContext, args: ScrapeTendersArgs) -> dict[str, Any]:
    client = PoliteClient()
    reports = []
    for source in build_sources(args.sources or None):
        report = await source.collect(client)
        await record_source_health(context.session, report)
        if report.ok:
            await ingest_report(context.session, report, run_id=context.run_id)
        reports.append(report)

    await archive(
        RAW_TOOL_RESPONSES,
        uuid.uuid4(),
        {
            "reports": [
                {"source": r.source_key, "ok": r.ok, "count": len(r.tenders), "error": r.error}
                for r in reports
            ]
        },
        run_id=str(context.run_id),
        tool_name="scrape_tenders",
    )

    # Degraded sources are named, not hidden: a report that silently omits a
    # source is indistinguishable from one where that source had no tenders.
    return {
        "sources": [
            {
                "source": r.source_key,
                "ok": r.ok,
                "tenders_found": len(r.tenders),
                "error": r.error,
            }
            for r in reports
        ],
        "working": [r.source_key for r in reports if r.ok and r.tenders],
        "degraded": [r.source_key for r in reports if not r.ok],
    }


class WebSearchArgs(BaseModel):
    query: str
    domain: str | None = Field(default=None, description="Restrict to one site.")


async def web_search(context: ToolContext, args: WebSearchArgs) -> dict[str, Any]:
    source = WebSearchSource(domain=args.domain, query=args.query)
    tenders = await source.search()
    return {
        "count": len(tenders),
        "results": [{"title": t.title, "url": t.source_url} for t in tenders],
        "note": "From web search, not the source site. Closing dates are not reliable here.",
    }


# --- CRM ---------------------------------------------------------------------


class CrmReadArgs(BaseModel):
    module: str = Field(description="Leads, Contacts, Deals or Notes.")
    criteria: str | None = Field(default=None, description="COQL where-clause.")
    limit: int = Field(default=10, ge=1, le=50)


async def crm_read(context: ToolContext, args: CrmReadArgs) -> dict[str, Any]:
    records = await ZohoClient(context.session, context.user_id).search(
        args.module, args.criteria, args.limit
    )
    return {"module": args.module, "count": len(records), "records": records}


class ProposeCrmEntryArgs(BaseModel):
    module: str = Field(description="Leads or Notes.")
    payload: dict[str, Any] = Field(description="Field values to write.")
    rationale: str = Field(description="Why this write is worth making.")
    record_id: str | None = Field(default=None, description="Set to update an existing record.")


async def propose_crm_entry(context: ToolContext, args: ProposeCrmEntryArgs) -> dict[str, Any]:
    """Queue a CRM write for human approval. Never touches Zoho.

    This is the only path by which an untrusted run can affect the CRM at all,
    and all it can do is ask.
    """
    if args.module not in WRITABLE_MODULES:
        raise ModuleNotAllowedError(
            f"{args.module} is not writable. Allowed: {sorted(WRITABLE_MODULES)}."
        )

    kept, dropped = filter_payload(args.module, args.payload)
    if not kept:
        raise ValueError(
            f"No writable fields in the payload. Allowed for {args.module}: "
            f"{sorted(filter_payload(args.module, {})[0]) or 'see FIELD_WHITELIST'}."
        )

    existing_count = (
        await context.session.execute(
            select(func.count(Approval.id)).where(Approval.run_id == context.run_id)
        )
    ).scalar_one()
    if existing_count >= MAX_PROPOSALS_PER_RUN:
        raise ValueError(
            f"This run has already queued {MAX_PROPOSALS_PER_RUN} proposals, which is the cap."
        )

    current = None
    if args.record_id:
        try:
            current = await ZohoClient(context.session, context.user_id).get(
                args.module, args.record_id
            )
        except Exception as exc:  # noqa: BLE001 — a diff is nice, not essential
            log.warning("crm.diff_lookup_failed", error_type=type(exc).__name__)

    approval = Approval(
        user_id=context.user_id,
        run_id=context.run_id,
        module=args.module,
        operation="update" if args.record_id else "create",
        record_id=args.record_id,
        proposed_payload=kept,
        diff=compute_diff(current, kept),
        rationale=args.rationale,
        expires_at=datetime.now(UTC) + APPROVAL_TTL,
    )
    context.session.add(approval)
    await context.session.flush()

    log.info(
        "crm.proposed",
        approval_id=str(approval.id),
        module=args.module,
        operation=approval.operation,
        dropped_fields=dropped,
    )
    return {
        "approval_id": str(approval.id),
        "status": "pending",
        "module": args.module,
        "operation": approval.operation,
        "fields": sorted(kept),
        "dropped_fields": dropped,
        "expires_at": approval.expires_at.isoformat(),
        "note": "Queued for human approval. Nothing has been written to the CRM.",
    }


class CommitCrmWriteArgs(BaseModel):
    approval_id: str = Field(description="An approval a human has already approved.")


async def commit_crm_write(context: ToolContext, args: CommitCrmWriteArgs) -> dict[str, Any]:
    """Execute an approved write.

    Refuses anything not already in `approved` state, so the tool cannot be used
    to originate a write even from a trusted turn — the human's click is what
    moves an approval into that state, and there is no other way in.
    """
    from batanat_api.approvals.service import execute_approval

    result = await execute_approval(
        context.session, uuid.UUID(args.approval_id), user_id=context.user_id
    )
    return result


class ApprovePendingArgs(BaseModel):
    approval_id: str
    decision: str = Field(default="approve", description="approve | reject")
    reason: str | None = None


async def approve_pending(context: ToolContext, args: ApprovePendingArgs) -> dict[str, Any]:
    """Approve or reject a queued proposal on behalf of a verified WhatsApp sender."""
    from batanat_api.approvals.service import decide_approval

    return await decide_approval(
        context.session,
        uuid.UUID(args.approval_id),
        user_id=context.user_id,
        approve=args.decision == "approve",
        actor="whatsapp",
        reason=args.reason,
    )


class MaintenanceArgs(BaseModel):
    task: str = Field(description="Which maintenance task to run.")


async def internal_maintenance(context: ToolContext, args: MaintenanceArgs) -> dict[str, Any]:
    from batanat_api.scheduler.maintenance import run_task

    return await run_task(context.session, args.task, user_id=context.user_id)


# --- tender lookup used by the report builder --------------------------------


async def recent_tenders(session, *, since: datetime, limit: int = 200) -> list[Tender]:
    return list(
        (
            await session.execute(
                select(Tender)
                .where(Tender.first_seen_at >= since)
                .order_by(Tender.closing_date.asc().nulls_last())
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )


def register_all() -> None:
    """Register every real tool. Called once, from `agent.tools.__init__`."""
    for spec in [
        ToolSpec(
            name="read_email",
            description=(
                "Read recent emails from the connected Gmail account. Returns cleaned "
                "bodies with quoted history and signatures removed."
            ),
            args_model=ReadEmailsArgs,
            handler=read_emails,
        ),
        ToolSpec(
            name="read_thread",
            description=(
                "Read the full conversation an email belongs to, oldest message first. "
                "Use this when one message is not enough to judge — the deadline or the "
                "actual ask is often earlier in the thread."
            ),
            args_model=ReadThreadArgs,
            handler=read_thread,
        ),
        ToolSpec(
            name="classify_email",
            description=(
                "Record your classification of an email you have read, scored against "
                "the operating criteria in your instructions."
            ),
            args_model=ClassifyEmailArgs,
            handler=classify_email,
        ),
        ToolSpec(
            name="scrape_tenders",
            description="Fetch and store current tender listings from the configured sources.",
            args_model=ScrapeTendersArgs,
            handler=scrape_tenders,
        ),
        ToolSpec(
            name="web_search",
            description="Search the web for tender notices the scrapers could not reach.",
            args_model=WebSearchArgs,
            handler=web_search,
        ),
        ToolSpec(
            name="crm_read",
            description="Search Zoho CRM. Read-only.",
            args_model=CrmReadArgs,
            handler=crm_read,
        ),
        ToolSpec(
            name="propose_crm_entry",
            description=(
                "Propose a CRM write for human approval. This does NOT write to the CRM. "
                "It queues a proposal and returns an approval id."
            ),
            args_model=ProposeCrmEntryArgs,
            handler=propose_crm_entry,
        ),
        ToolSpec(
            name="commit_crm_write",
            description="Execute a CRM write that a human has already approved.",
            args_model=CommitCrmWriteArgs,
            handler=commit_crm_write,
            is_write=True,
        ),
        ToolSpec(
            name="approve_pending",
            description="Approve or reject a queued CRM proposal.",
            args_model=ApprovePendingArgs,
            handler=approve_pending,
            is_write=True,
        ),
        ToolSpec(
            name="internal_maintenance",
            description="Run an internal maintenance task.",
            args_model=MaintenanceArgs,
            handler=internal_maintenance,
        ),
    ]:
        register(spec)
