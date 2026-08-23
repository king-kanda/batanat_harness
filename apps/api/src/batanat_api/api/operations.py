"""The operational API: dashboard, activity, results, approvals, rules, memory, chat.

Read endpoints are plain queries. The two that change something outside the
system — approving a write, and chat — are the only ones that can reach the
CRM, and both go through the approval queue.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter, File, Form, HTTPException, Query, UploadFile, status
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import selectinload

from batanat_api.agent import skill as skill_service
from batanat_api.approvals import service as approvals
from batanat_api.config import get_settings
from batanat_api.contracts.operations import (
    ApprovalDiffEntry,
    ApprovalView,
    ChatRequest,
    ChatResponse,
    DashboardView,
    DiffLine,
    DocumentView,
    EmailView,
    FeedbackRequest,
    MemoryView,
    ReportView,
    RunView,
    ScheduledRunView,
    SkillDraftRequest,
    SkillDraftResponse,
    SkillValidationView,
    SkillVersionView,
    SourceHealthView,
    TenderSourceRequest,
    TenderSourceView,
    TenderView,
    ToolCallView,
)
from batanat_api.core.deps import CurrentUser, SessionDep
from batanat_api.core.logging import get_logger
from batanat_api.db import enums
from batanat_api.db.models import (
    Approval,
    Connection,
    Email,
    Feedback,
    Memory,
    Run,
    SkillVersion,
    Tender,
    TenderSourceRow,
)

log = get_logger(__name__)

router = APIRouter(prefix="/api", tags=["operations"])


# --- serialisation helpers ---------------------------------------------------


def _run_view(
    run: Run, *, skill_version: int | None = None, include_calls: bool = False
) -> RunView:
    return RunView(
        id=run.id,
        trigger_type=run.trigger_type,
        trust_level=run.trust_level,
        bound_tools=list(run.bound_tools or []),
        status=run.status,
        trigger_ref=run.trigger_ref,
        started_at=run.started_at,
        ended_at=run.ended_at,
        duration_ms=run.duration_ms,
        token_cost=run.token_cost,
        iterations=run.iterations,
        error=run.error,
        summary=run.summary,
        skill_version=skill_version,
        tool_calls=[
            ToolCallView(
                sequence=c.sequence,
                tool_name=c.tool_name,
                arguments=c.arguments,
                result=c.result,
                error=c.error,
                duration_ms=c.duration_ms,
                token_cost=c.token_cost,
                started_at=c.started_at,
            )
            for c in (run.tool_calls if include_calls else [])
        ],
    )


def _approval_view(approval: Approval, *, now: datetime) -> ApprovalView:
    return ApprovalView(
        id=approval.id,
        module=approval.module,
        operation=approval.operation,
        record_id=approval.record_id,
        status=approval.status,
        rationale=approval.rationale,
        proposed_payload=approval.proposed_payload,
        diff=[
            ApprovalDiffEntry(field=k, current=v.get("current"), proposed=v.get("proposed"))
            for k, v in (approval.diff or {}).items()
        ],
        expires_at=approval.expires_at,
        hours_remaining=round((approval.expires_at - now).total_seconds() / 3600, 1),
        created_at=approval.created_at,
        executed_at=approval.executed_at,
        execution_result=approval.execution_result,
        run_id=approval.run_id,
    )


def _tender_view(tender: Tender, *, now: datetime, feedback: str | None = None) -> TenderView:
    return TenderView(
        id=tender.id,
        source=tender.source,
        reference_no=tender.reference_no,
        title=tender.title,
        entity=tender.entity,
        category=tender.category,
        closing_date=tender.closing_date,
        estimated_value=float(tender.estimated_value) if tender.estimated_value else None,
        currency=tender.currency,
        source_url=tender.source_url,
        county=tender.county,
        first_seen_at=tender.first_seen_at,
        is_closed=bool(tender.closing_date and tender.closing_date < now),
        feedback=feedback,
    )


# --- dashboard ---------------------------------------------------------------


@router.get("/dashboard", response_model=DashboardView)
async def dashboard(session: SessionDep, user: CurrentUser) -> DashboardView:
    from batanat_api.scheduler.jobs import next_run_times

    now = datetime.now(UTC)
    since = now - timedelta(hours=24)
    settings = get_settings()

    opportunities = (
        await session.execute(
            select(func.count(Email.id)).where(
                Email.user_id == user.id,
                Email.category == enums.EmailCategory.opportunity,
                Email.processed_at >= since,
            )
        )
    ).scalar_one()

    tenders_today = (
        await session.execute(select(func.count(Tender.id)).where(Tender.first_seen_at >= since))
    ).scalar_one()

    pending = (
        await session.execute(
            select(func.count(Approval.id)).where(
                Approval.user_id == user.id, Approval.status == enums.ApprovalStatus.pending
            )
        )
    ).scalar_one()

    connections = (
        (
            await session.execute(
                select(Connection).where(
                    Connection.user_id == user.id,
                    Connection.status != enums.ConnectionStatus.revoked,
                )
            )
        )
        .scalars()
        .all()
    )
    needs_attention = [
        c.provider.value for c in connections if c.status is not enums.ConnectionStatus.connected
    ]

    sources = (
        (await session.execute(select(TenderSourceRow).order_by(TenderSourceRow.key)))
        .scalars()
        .all()
    )

    recent = (
        (
            await session.execute(
                select(Run).where(Run.user_id == user.id).order_by(Run.started_at.desc()).limit(5)
            )
        )
        .scalars()
        .all()
    )

    return DashboardView(
        generated_at=now,
        opportunities_today=opportunities,
        tenders_today=tenders_today,
        pending_approvals=pending,
        connections_healthy=len(connections) - len(needs_attention),
        connections_total=len(connections),
        connections_needing_attention=needs_attention,
        sources=[
            SourceHealthView(
                key=s.key,
                name=s.name,
                health=s.health,
                last_ok_at=s.last_ok_at,
                last_error=s.last_error,
                consecutive_failures=s.consecutive_failures,
            )
            for s in sources
        ],
        next_runs=[ScheduledRunView(**job) for job in next_run_times()],
        recent_runs=[_run_view(r) for r in recent],
        kill_switch=settings.kill_switch,
        crm_dry_run=settings.crm_dry_run,
    )


# --- activity ----------------------------------------------------------------


@router.get("/runs", response_model=list[RunView])
async def list_runs(
    session: SessionDep, user: CurrentUser, limit: int = Query(default=50, le=200)
) -> list[RunView]:
    runs = (
        (
            await session.execute(
                select(Run)
                .where(Run.user_id == user.id)
                .order_by(Run.started_at.desc())
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )
    return [_run_view(r) for r in runs]


@router.get("/runs/{run_id}", response_model=RunView)
async def get_run(run_id: uuid.UUID, session: SessionDep, user: CurrentUser) -> RunView:
    run = (
        await session.execute(
            select(Run)
            .options(selectinload(Run.tool_calls))
            .where(Run.id == run_id, Run.user_id == user.id)
        )
    ).scalar_one_or_none()
    if run is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such run.")

    version = None
    if run.skill_version_id:
        version = (
            await session.execute(
                select(SkillVersion.version).where(SkillVersion.id == run.skill_version_id)
            )
        ).scalar_one_or_none()

    return _run_view(run, skill_version=version, include_calls=True)


@router.get("/policy", summary="The capability table, as shipped")
async def policy() -> dict[str, Any]:
    """What each trigger is allowed to do. Rendered on the Activity screen."""
    from batanat_api.agent.capabilities import audit_policy

    return audit_policy()


# --- results -----------------------------------------------------------------


@router.get("/emails", response_model=list[EmailView])
async def list_emails(
    session: SessionDep,
    user: CurrentUser,
    category: str | None = None,
    limit: int = Query(default=50, le=200),
) -> list[EmailView]:
    query = select(Email).where(Email.user_id == user.id)
    if category:
        query = query.where(Email.category == enums.EmailCategory(category))

    emails = (
        (await session.execute(query.order_by(Email.received_at.desc().nulls_last()).limit(limit)))
        .scalars()
        .all()
    )

    votes = dict(
        (
            await session.execute(
                select(Feedback.subject_id, Feedback.rating).where(
                    Feedback.user_id == user.id, Feedback.subject_type == "email"
                )
            )
        ).all()
    )

    return [
        EmailView(
            id=e.id,
            from_address=e.from_address,
            from_name=e.from_name,
            subject=e.subject,
            snippet=e.snippet,
            received_at=e.received_at,
            category=e.category,
            priority=e.priority,
            confidence=float(e.confidence) if e.confidence else None,
            reasoning=(e.classification or {}).get("reasoning"),
            suggested_action=(e.classification or {}).get("suggested_action"),
            feedback=votes.get(e.id).value if votes.get(e.id) else None,
        )
        for e in emails
    ]


@router.get("/tenders", response_model=list[TenderView])
async def list_tenders(
    session: SessionDep,
    user: CurrentUser,
    include_closed: bool = False,
    limit: int = Query(default=100, le=500),
) -> list[TenderView]:
    now = datetime.now(UTC)
    query = select(Tender)
    if not include_closed:
        query = query.where((Tender.closing_date.is_(None)) | (Tender.closing_date >= now))

    tenders = (
        (await session.execute(query.order_by(Tender.closing_date.asc().nulls_last()).limit(limit)))
        .scalars()
        .all()
    )

    votes = dict(
        (
            await session.execute(
                select(Feedback.subject_id, Feedback.rating).where(
                    Feedback.user_id == user.id, Feedback.subject_type == "tender"
                )
            )
        ).all()
    )

    return [
        _tender_view(t, now=now, feedback=votes.get(t.id).value if votes.get(t.id) else None)
        for t in tenders
    ]


@router.post("/feedback", status_code=204)
async def submit_feedback(body: FeedbackRequest, session: SessionDep, user: CurrentUser) -> None:
    """A thumb up or down. Becomes a labelled eval case — see `make eval`."""
    if body.subject_type not in {"email", "tender"}:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "subject_type must be email or tender.")

    active = await skill_service.get_active(session, user.id)
    await session.execute(
        insert(Feedback)
        .values(
            id=uuid.uuid4(),
            user_id=user.id,
            subject_type=body.subject_type,
            subject_id=body.subject_id,
            rating=enums.FeedbackRating(body.rating),
            reason=body.reason,
            skill_version_id=active.id if active else None,
            created_at=datetime.now(UTC),
        )
        # Changing your mind replaces the vote rather than failing.
        .on_conflict_do_update(
            index_elements=["user_id", "subject_type", "subject_id"],
            set_={"rating": enums.FeedbackRating(body.rating), "reason": body.reason},
        )
    )


# --- approvals ---------------------------------------------------------------


@router.get("/approvals", response_model=list[ApprovalView])
async def list_approvals(
    session: SessionDep,
    user: CurrentUser,
    status_filter: str | None = Query(default=None, alias="status"),
) -> list[ApprovalView]:
    now = datetime.now(UTC)
    query = select(Approval).where(Approval.user_id == user.id)
    if status_filter:
        query = query.where(Approval.status == enums.ApprovalStatus(status_filter))

    rows = (
        (await session.execute(query.order_by(Approval.created_at.desc()).limit(100)))
        .scalars()
        .all()
    )
    return [_approval_view(a, now=now) for a in rows]


@router.post("/approvals/{approval_id}/approve", response_model=dict)
async def approve(
    approval_id: uuid.UUID,
    session: SessionDep,
    user: CurrentUser,
    edited_payload: dict[str, Any] | None = None,
) -> dict:
    """Approve, optionally with edits. Executes immediately, without an LLM."""
    try:
        return await approvals.decide_approval(
            session,
            approval_id,
            user_id=user.id,
            approve=True,
            actor="web",
            edited_payload=edited_payload,
        )
    except approvals.ApprovalNotFoundError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such approval.") from None
    except approvals.ApprovalStateError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from None


@router.post("/approvals/{approval_id}/reject", response_model=dict)
async def reject(
    approval_id: uuid.UUID, session: SessionDep, user: CurrentUser, reason: str | None = None
) -> dict:
    try:
        return await approvals.decide_approval(
            session, approval_id, user_id=user.id, approve=False, actor="web", reason=reason
        )
    except approvals.ApprovalNotFoundError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such approval.") from None
    except approvals.ApprovalStateError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from None


# --- rules -------------------------------------------------------------------


@router.get("/skill", response_model=list[SkillVersionView])
async def list_skill_versions(session: SessionDep, user: CurrentUser) -> list[SkillVersionView]:
    return [
        SkillVersionView(
            id=v.id,
            version=v.version,
            is_active=v.is_active,
            content=v.content,
            checksum=v.checksum,
            created_by=v.created_by,
            notes=v.notes,
            created_at=v.created_at,
        )
        for v in await skill_service.list_versions(session, user.id)
    ]


@router.post("/skill/validate", response_model=SkillValidationView)
async def validate_skill(body: dict[str, str]) -> SkillValidationView:
    """Live validation for the editor. Same rules as save."""
    result = skill_service.validate_skill_content(body.get("content", ""))
    return SkillValidationView(ok=result.ok, errors=result.errors, warnings=result.warnings)


@router.post("/skill", response_model=SkillVersionView)
async def publish_skill(
    body: dict[str, str], session: SessionDep, user: CurrentUser
) -> SkillVersionView:
    try:
        version = await skill_service.publish(
            session, user.id, body.get("content", ""), notes=body.get("notes")
        )
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from None

    return SkillVersionView(
        id=version.id,
        version=version.version,
        is_active=version.is_active,
        content=version.content,
        checksum=version.checksum,
        created_by=version.created_by,
        notes=version.notes,
        created_at=version.created_at,
    )


@router.post("/skill/draft", response_model=SkillDraftResponse, summary="Draft rules with help")
async def draft_skill(body: SkillDraftRequest, user: CurrentUser) -> SkillDraftResponse:
    """Talk through the criteria and get a complete document back.

    No tools are bound to this — it is a conversation about the business, not an
    agent run. Whatever it produces lands in the editor and is validated like
    anything else; publishing is still a human pressing a button.
    """
    from batanat_api.agent.skill_assistant import draft_rules

    try:
        result = await draft_rules([m.model_dump() for m in body.messages], body.current_content)
    except RuntimeError as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from None
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY, f"The model call failed: {type(exc).__name__}"
        ) from None

    validation = None
    if result.proposed_content:
        checked = skill_service.validate_skill_content(result.proposed_content)
        validation = SkillValidationView(
            ok=checked.ok, errors=checked.errors, warnings=checked.warnings
        )

    return SkillDraftResponse(
        reply=result.reply, proposed_content=result.proposed_content, validation=validation
    )


@router.post("/skill/{version_number}/rollback", response_model=SkillVersionView)
async def rollback_skill(
    version_number: int, session: SessionDep, user: CurrentUser
) -> SkillVersionView:
    try:
        version = await skill_service.rollback_to(session, user.id, version_number)
    except ValueError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from None

    return SkillVersionView(
        id=version.id,
        version=version.version,
        is_active=version.is_active,
        content=version.content,
        checksum=version.checksum,
        created_by=version.created_by,
        notes=version.notes,
        created_at=version.created_at,
    )


@router.get("/skill/diff", response_model=list[DiffLine])
async def diff_skill(session: SessionDep, user: CurrentUser, old: int, new: int) -> list[DiffLine]:
    versions = {v.version: v for v in await skill_service.list_versions(session, user.id)}
    if old not in versions or new not in versions:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown version.")
    return [
        DiffLine(**line)
        for line in skill_service.diff_versions(versions[old].content, versions[new].content)
    ]


# --- memory ------------------------------------------------------------------


@router.get("/memories", response_model=list[MemoryView])
async def list_memories(
    session: SessionDep, user: CurrentUser, search: str | None = None, limit: int = 100
) -> list[MemoryView]:
    query = select(Memory).where(Memory.user_id == user.id)
    if search:
        query = query.where(Memory.content.ilike(f"%{search}%"))

    rows = (
        (await session.execute(query.order_by(Memory.created_at.desc()).limit(limit)))
        .scalars()
        .all()
    )
    return [
        MemoryView(
            id=m.id,
            layer=m.layer.value,
            trust_tag=m.trust_tag.value,
            content=m.content,
            source_ref=m.source_ref,
            created_at=m.created_at,
            instruction_eligible=m.trust_tag is not enums.TrustTag.untrusted_external,
        )
        for m in rows
    ]


@router.delete("/memories/{memory_id}", status_code=204)
async def delete_memory(memory_id: uuid.UUID, session: SessionDep, user: CurrentUser) -> None:
    from batanat_api.memory.store import forget

    if not await forget(session, user.id, memory_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such memory.")


# --- tender sources ----------------------------------------------------------


def _source_view(row: TenderSourceRow) -> TenderSourceView:
    return TenderSourceView(
        key=row.key,
        name=row.name,
        entity=row.entity,
        listing_url=row.listing_url or row.base_url,
        fallback_urls=list(row.fallback_urls or []),
        is_enabled=row.is_enabled,
        is_custom=row.is_custom,
        health=row.health,
        last_ok_at=row.last_ok_at,
        last_error=row.last_error,
        consecutive_failures=row.consecutive_failures,
    )


@router.get("/sources", response_model=list[TenderSourceView])
async def list_sources(session: SessionDep, user: CurrentUser) -> list[TenderSourceView]:
    rows = (
        (await session.execute(select(TenderSourceRow).order_by(TenderSourceRow.key)))
        .scalars()
        .all()
    )
    return [_source_view(row) for row in rows]


@router.post("/sources", response_model=TenderSourceView, status_code=201)
async def create_source(
    body: TenderSourceRequest, session: SessionDep, user: CurrentUser
) -> TenderSourceView:
    """Add a site to the sweep.

    The key is derived from the host rather than asked for: it is an internal
    identifier, and making someone invent one is a question with no good answer.
    """
    from urllib.parse import urlsplit

    parts = urlsplit(body.listing_url)
    if parts.scheme not in {"http", "https"} or not parts.netloc:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "The listing URL must be a full http(s) address, e.g. https://example.co.ke/tenders.",
        )

    host = parts.netloc.lower().removeprefix("www.")
    key = re.sub(r"[^a-z0-9]+", "-", host.split(".")[0])[:50] or "source"

    # Keys must be unique; suffix rather than reject, since two sites can share
    # a first label (kplc.co.ke and kplc.com).
    existing = {row for row in (await session.execute(select(TenderSourceRow.key))).scalars().all()}
    candidate, suffix = key, 2
    while candidate in existing:
        candidate = f"{key}-{suffix}"
        suffix += 1

    row = TenderSourceRow(
        key=candidate,
        name=body.name,
        entity=body.entity or body.name,
        base_url=f"{parts.scheme}://{parts.netloc}",
        listing_url=body.listing_url,
        fallback_urls=[],
        adapter="TableTenderSource",
        is_enabled=body.is_enabled,
        is_custom=True,
        health=enums.SourceHealth.ok,
    )
    session.add(row)
    await session.flush()

    log.info("source.created", key=row.key, listing_url=row.listing_url)
    return _source_view(row)


@router.patch("/sources/{key}", response_model=TenderSourceView)
async def update_source(
    key: str, body: dict[str, Any], session: SessionDep, user: CurrentUser
) -> TenderSourceView:
    """Rename, re-point, enable or disable a source.

    Disabling works for the shipped five as well — a site you would rather not
    fetch at all is turned off here rather than removed from the code.
    """
    row = (
        await session.execute(select(TenderSourceRow).where(TenderSourceRow.key == key))
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such source.")

    if "is_enabled" in body:
        row.is_enabled = bool(body["is_enabled"])
    if body.get("name"):
        row.name = str(body["name"])[:200]
    if body.get("entity"):
        row.entity = str(body["entity"])[:300]
    if body.get("listing_url"):
        row.listing_url = str(body["listing_url"])[:500]
        # A new URL deserves a clean slate rather than inherited failures.
        row.health = enums.SourceHealth.ok
        row.consecutive_failures = 0
        row.last_error = None

    await session.flush()
    log.info("source.updated", key=key)
    return _source_view(row)


@router.delete("/sources/{key}", status_code=204)
async def delete_source(key: str, session: SessionDep, user: CurrentUser) -> None:
    """Remove a source the user added. The shipped five can only be disabled."""
    row = (
        await session.execute(select(TenderSourceRow).where(TenderSourceRow.key == key))
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such source.")
    if not row.is_custom:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"{row.name} ships with the system. Disable it instead of deleting it.",
        )

    await session.delete(row)
    await session.flush()
    log.info("source.deleted", key=key)


# --- knowledge base ---------------------------------------------------------


@router.get("/knowledge", response_model=list[DocumentView])
async def list_knowledge(session: SessionDep, user: CurrentUser) -> list[DocumentView]:
    from batanat_api.knowledge.documents import list_documents

    return [DocumentView(**asdict(summary)) for summary in await list_documents(session, user.id)]


@router.post("/knowledge", response_model=DocumentView)
async def upload_knowledge(
    session: SessionDep,
    user: CurrentUser,
    # B008 is about mutable defaults; FastAPI's File/Form markers are the
    # documented way to declare multipart parts, so the rule is silenced here
    # rather than worked around.
    file: UploadFile = File(...),  # noqa: B008
    trust_tag: str = Form(default="user_asserted"),  # noqa: B008
) -> DocumentView:
    """Upload a document into semantic memory.

    `trust_tag` is the caller's declaration about provenance, and it is load
    bearing: `user_asserted` content can inform the agent directly, while
    `untrusted_external` is retrievable but only ever rendered as quoted data.
    A third-party PDF can carry the same injection text an email can.
    """
    from batanat_api.knowledge.documents import (
        EmptyDocumentError,
        UnsupportedDocumentError,
        ingest_document,
    )

    try:
        tag = enums.TrustTag(trust_tag)
    except ValueError:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"trust_tag must be one of {[t.value for t in enums.TrustTag]}.",
        ) from None

    if tag is enums.TrustTag.system_derived:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "system_derived is reserved for things this system observed; an upload is not one.",
        )

    data = await file.read()
    try:
        summary = await ingest_document(
            session,
            user_id=user.id,
            filename=file.filename or "upload",
            content_type=file.content_type or "",
            data=data,
            trust_tag=tag,
        )
    except (UnsupportedDocumentError, EmptyDocumentError, ValueError) as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from None

    return DocumentView(**asdict(summary))


@router.delete("/knowledge/{document_id}", status_code=204)
async def delete_knowledge(document_id: uuid.UUID, session: SessionDep, user: CurrentUser) -> None:
    from batanat_api.knowledge.documents import delete_document

    if not await delete_document(session, user.id, document_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such document.")


# --- reports -----------------------------------------------------------------


@router.get("/reports/tenders/{label}", response_model=ReportView)
async def tender_report(label: str, session: SessionDep, user: CurrentUser) -> ReportView:
    """The permalink page, reconstructed from the run that produced it."""
    run = (
        await session.execute(
            select(Run).where(
                Run.user_id == user.id,
                Run.trigger_type == enums.TriggerType.cron_tender,
                Run.trigger_ref == label,
            )
        )
    ).scalar_one_or_none()
    if run is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"No tender report for {label}.")

    now = datetime.now(UTC)
    tenders = (
        (
            await session.execute(
                select(Tender)
                .where(Tender.first_seen_run_id == run.id)
                .order_by(Tender.closing_date.asc().nulls_last())
            )
        )
        .scalars()
        .all()
    )
    sources = (await session.execute(select(TenderSourceRow))).scalars().all()

    return ReportView(
        label=label,
        run_id=run.id,
        generated_at=run.started_at,
        lookback_hours=24,
        tenders=[_tender_view(t, now=now) for t in tenders],
        failed_sources=[s.key for s in sources if s.health is enums.SourceHealth.failing],
        validation={"accepted": len(tenders)},
    )


# --- chat --------------------------------------------------------------------


@router.post("/chat", response_model=ChatResponse)
async def chat(body: ChatRequest, session: SessionDep, user: CurrentUser) -> ChatResponse:
    """A trusted turn: the full toolbelt, but writes still queue for approval."""
    from batanat_api.agent.providers import get_model
    from batanat_api.agent.runner import AgentRunner, KillSwitchEngagedError
    from batanat_api.memory.store import assemble

    model = get_model()
    if not model.is_configured():
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "No model API key is set for the selected LLM_PROVIDER — see TODO.md.",
        )

    active = await skill_service.get_active(session, user.id)
    memory = await assemble(
        session, user.id, query=body.message, skill_content=active.content if active else None
    )

    try:
        result = await AgentRunner(model=model).run(
            session,
            user_id=user.id,
            trigger=enums.TriggerType.web_chat,
            instruction=body.message,
            skill_content=active.content if active else None,
            skill_version_id=active.id if active else None,
            memories=memory.system_prompt_lines(),
            # Memories derived from email or scraped pages travel as quoted
            # data, never as instruction. Retrieved and then dropped would be
            # safe but dishonest — the trust split only means something if the
            # untrusted half actually goes somewhere.
            quoted_context=memory.quoted_blocks(),
        )
    except KillSwitchEngagedError as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from None

    return ChatResponse(
        run_id=result.run_id,
        reply=result.output,
        bound_tools=result.bound_tools,
        tool_calls=result.tool_calls,
        status=result.status,
    )


# --- manual triggers ---------------------------------------------------------


@router.post("/sync/gmail", response_model=dict)
async def sync_gmail(session: SessionDep, user: CurrentUser) -> dict:
    """The 'Sync now' button."""
    from batanat_api.triggers.gmail_trigger import sync_now

    try:
        return await sync_now(session, user.id)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"{type(exc).__name__}: {exc}") from None


@router.post("/sync/tenders", response_model=dict)
async def sync_tenders(session: SessionDep, user: CurrentUser, notify: bool = False) -> dict:
    """Run a tender cycle now, for demos and for testing the pipeline."""
    from batanat_api.notifications.dispatcher import dispatch_tender_report
    from batanat_api.triggers.tender_trigger import run_tender_cycle

    report = await run_tender_cycle(session, user.id)
    if notify:
        report["dispatch"] = await dispatch_tender_report(session, user.id, report)
    return report
