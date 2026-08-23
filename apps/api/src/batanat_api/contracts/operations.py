"""Contracts for the operational screens: dashboard, activity, results, approvals, rules."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from batanat_api.db.enums import (
    ApprovalStatus,
    EmailCategory,
    Priority,
    RunStatus,
    SourceHealth,
    TriggerType,
    TrustLevel,
)


class ToolCallView(BaseModel):
    """One audited tool call, as the Activity screen shows it."""

    sequence: int
    tool_name: str
    arguments: dict[str, Any]
    result: dict[str, Any] | None = None
    error: str | None = None
    duration_ms: int | None = None
    token_cost: int = 0
    started_at: datetime


class RunView(BaseModel):
    id: uuid.UUID
    trigger_type: TriggerType
    trust_level: TrustLevel
    bound_tools: list[str] = Field(
        description="Exactly the tools this run was handed, recorded before the model ran."
    )
    status: RunStatus
    trigger_ref: str | None = None
    started_at: datetime
    ended_at: datetime | None = None
    duration_ms: int | None = None
    token_cost: int = 0
    iterations: int = 0
    error: str | None = None
    summary: str | None = None
    skill_version: int | None = None
    tool_calls: list[ToolCallView] = Field(default_factory=list)


class ApprovalDiffEntry(BaseModel):
    field: str
    current: Any = None
    proposed: Any = None


class ApprovalView(BaseModel):
    id: uuid.UUID
    module: str
    operation: str
    record_id: str | None = None
    status: ApprovalStatus
    rationale: str | None = None
    proposed_payload: dict[str, Any]
    diff: list[ApprovalDiffEntry]
    expires_at: datetime
    hours_remaining: float
    created_at: datetime
    executed_at: datetime | None = None
    execution_result: dict[str, Any] | None = None
    run_id: uuid.UUID | None = None


class EmailView(BaseModel):
    id: uuid.UUID
    from_address: str | None = None
    from_name: str | None = None
    subject: str | None = None
    snippet: str | None = None
    received_at: datetime | None = None
    category: EmailCategory | None = None
    priority: Priority | None = None
    confidence: float | None = None
    reasoning: str | None = None
    suggested_action: str | None = None
    feedback: str | None = None


class TenderView(BaseModel):
    id: uuid.UUID
    source: str
    reference_no: str | None = None
    title: str
    entity: str | None = None
    category: str | None = None
    closing_date: datetime | None = None
    estimated_value: float | None = None
    currency: str | None = None
    source_url: str
    county: str | None = None
    first_seen_at: datetime
    is_closed: bool = False
    feedback: str | None = None


class SourceHealthView(BaseModel):
    key: str
    name: str
    health: SourceHealth
    last_ok_at: datetime | None = None
    last_error: str | None = None
    consecutive_failures: int = 0


class ScheduledRunView(BaseModel):
    id: str
    next_run_at: str


class DashboardView(BaseModel):
    """Everything the dashboard needs, in one request."""

    generated_at: datetime
    opportunities_today: int
    tenders_today: int
    pending_approvals: int
    connections_healthy: int
    connections_total: int
    connections_needing_attention: list[str] = Field(default_factory=list)
    sources: list[SourceHealthView] = Field(default_factory=list)
    next_runs: list[ScheduledRunView] = Field(default_factory=list)
    recent_runs: list[RunView] = Field(default_factory=list)
    kill_switch: bool = False
    crm_dry_run: bool = True


class SkillVersionView(BaseModel):
    id: uuid.UUID
    version: int
    is_active: bool
    content: str
    checksum: str
    created_by: str | None = None
    notes: str | None = None
    created_at: datetime


class SkillValidationView(BaseModel):
    ok: bool
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class DiffLine(BaseModel):
    type: str
    text: str


class MemoryView(BaseModel):
    id: uuid.UUID
    layer: str
    trust_tag: str
    content: str
    source_ref: str | None = None
    created_at: datetime
    instruction_eligible: bool = Field(
        description="False for untrusted-derived memory, which is only ever quoted as data."
    )


class DocumentView(BaseModel):
    """An uploaded knowledge-base document."""

    document_id: uuid.UUID
    filename: str
    trust_tag: str = Field(
        description="user_asserted may inform the agent directly; untrusted_external is "
        "only ever quoted as data."
    )
    chunk_count: int
    characters: int
    uploaded_at: datetime


class ReportView(BaseModel):
    """A tender report permalink page."""

    label: str
    run_id: uuid.UUID | None = None
    generated_at: datetime
    lookback_hours: int
    tenders: list[TenderView]
    failed_sources: list[str] = Field(default_factory=list)
    rejections: list[dict[str, str]] = Field(default_factory=list)
    validation: dict[str, Any] = Field(default_factory=dict)


class FeedbackRequest(BaseModel):
    subject_type: str = Field(description="email | tender")
    subject_id: uuid.UUID
    rating: str = Field(description="up | down")
    reason: str | None = None


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)


class ChatResponse(BaseModel):
    run_id: uuid.UUID
    reply: str | None
    bound_tools: list[str]
    tool_calls: list[dict[str, Any]] = Field(default_factory=list)
    status: RunStatus
