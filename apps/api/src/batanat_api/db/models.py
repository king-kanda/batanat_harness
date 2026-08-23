"""The relational schema.

Every dedupe rule in this system is a database constraint, never application
logic — delivery from Gmail Pub/Sub is at-least-once and unordered, scrapers
re-see the same tender twice a day, and a retried run must not double-write.
The constraints are the guarantee; the application only has to handle the
conflict.

Grouped by concern: identity → connections → agent runs → domain data →
delivery → memory.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from batanat_api.db import enums
from batanat_api.db.base import Base, CreatedAtMixin, TimestampMixin, uuid_pk


def pg_enum(enum_cls: type, name: str) -> Enum:
    """Native Postgres enum, storing the value (not the member name)."""
    return Enum(enum_cls, name=name, values_callable=lambda e: [m.value for m in e])


# ---------------------------------------------------------------------------
# Identity
# ---------------------------------------------------------------------------


class User(Base, TimestampMixin):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = uuid_pk()
    email: Mapped[str] = mapped_column(String(320), nullable=False, unique=True)
    name: Mapped[str | None] = mapped_column(String(200))
    timezone: Mapped[str] = mapped_column(String(64), nullable=False, default="Africa/Nairobi")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    #: scrypt hash, never a password. Null means the account cannot sign in yet.
    password_hash: Mapped[str | None] = mapped_column(String(255))
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    connections: Mapped[list[Connection]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )


# ---------------------------------------------------------------------------
# Connections and credentials
# ---------------------------------------------------------------------------


class Connection(Base, TimestampMixin):
    """One authorised link to an external provider.

    Tokens are stored as ciphertext produced by the token vault: a per-row data
    key encrypts the token, and the master key from the environment encrypts the
    data key. Nothing here is ever returned to the frontend.
    """

    __tablename__ = "connections"
    __table_args__ = (
        UniqueConstraint("user_id", "provider", "external_account"),
        Index("ix_connections_user_provider", "user_id", "provider"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    provider: Mapped[enums.Provider] = mapped_column(
        pg_enum(enums.Provider, "provider"), nullable=False
    )
    # Gmail address, Zoho org id, or the WhatsApp phone-number id.
    external_account: Mapped[str] = mapped_column(String(320), nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(200))

    # Zoho returns these per data centre. Never hardcode zohoapis.com — a DC
    # mismatch is the single most common integration failure.
    api_domain: Mapped[str | None] = mapped_column(String(255))
    accounts_url: Mapped[str | None] = mapped_column(String(255))

    scopes: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False, default=list)

    refresh_token_ciphertext: Mapped[bytes | None] = mapped_column(LargeBinary)
    refresh_token_key: Mapped[bytes | None] = mapped_column(LargeBinary)
    access_token_ciphertext: Mapped[bytes | None] = mapped_column(LargeBinary)
    access_token_key: Mapped[bytes | None] = mapped_column(LargeBinary)
    access_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    status: Mapped[enums.ConnectionStatus] = mapped_column(
        pg_enum(enums.ConnectionStatus, "connection_status"),
        nullable=False,
        default=enums.ConnectionStatus.connected,
    )
    last_error: Mapped[str | None] = mapped_column(Text)
    last_ok_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    user: Mapped[User] = relationship(back_populates="connections")


class GmailSyncState(Base, TimestampMixin):
    """Where the Gmail history cursor has reached, and when the watch expires.

    `history_id` advances only after a batch is fully processed; a crash
    mid-batch replays rather than skips.
    """

    __tablename__ = "gmail_sync_state"

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    connection_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("connections.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    history_id: Mapped[int | None] = mapped_column(BigInteger)
    watch_expiration: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    backfill_status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    backfill_total: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    backfill_done: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class WhatsAppLink(Base, TimestampMixin):
    """A phone number bound to a user via the pairing-code flow.

    `phone_e164` is globally unique: a number already linked to another user is
    rejected rather than silently rebound, so one person cannot capture
    another's alerts by pairing their number.
    """

    __tablename__ = "whatsapp_links"

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    phone_e164: Mapped[str] = mapped_column(String(20), nullable=False, unique=True)
    linked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class PairingCode(Base, CreatedAtMixin):
    """Short-lived code proving control of a phone number. Single use."""

    __tablename__ = "pairing_codes"
    __table_args__ = (Index("ix_pairing_codes_expires_at", "expires_at"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    code: Mapped[str] = mapped_column(String(16), nullable=False, unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    used_by_phone: Mapped[str | None] = mapped_column(String(20))


# ---------------------------------------------------------------------------
# Agent runs and audit
# ---------------------------------------------------------------------------


class SkillVersion(Base, CreatedAtMixin):
    """An immutable version of Skill.MD — the agent's procedural memory.

    Versions are never edited in place: the Rules editor writes a new row and
    flips `is_active`, so every run can be traced to the exact text that was
    live when it ran.
    """

    __tablename__ = "skill_versions"
    __table_args__ = (
        UniqueConstraint("user_id", "version"),
        Index(
            "uq_skill_versions_one_active_per_user",
            "user_id",
            unique=True,
            postgresql_where=text("is_active"),
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    checksum: Mapped[str] = mapped_column(String(64), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_by: Mapped[str | None] = mapped_column(String(200))
    notes: Mapped[str | None] = mapped_column(Text)


class Run(Base, CreatedAtMixin):
    """One invocation of the agent, from any trigger.

    `bound_tools` records what the capability resolver actually handed the
    model. It is the audit trail for the system's central security claim, so it
    is written at run start, before the model is called.
    """

    __tablename__ = "runs"
    __table_args__ = (
        Index("ix_runs_user_started", "user_id", "started_at"),
        Index("ix_runs_trigger_type", "trigger_type"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    trigger_type: Mapped[enums.TriggerType] = mapped_column(
        pg_enum(enums.TriggerType, "trigger_type"), nullable=False
    )
    trust_level: Mapped[enums.TrustLevel] = mapped_column(
        pg_enum(enums.TrustLevel, "trust_level"), nullable=False
    )
    bound_tools: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False, default=list)
    status: Mapped[enums.RunStatus] = mapped_column(
        pg_enum(enums.RunStatus, "run_status"), nullable=False, default=enums.RunStatus.running
    )
    skill_version_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("skill_versions.id", ondelete="SET NULL")
    )

    # Opaque reference to whatever caused the run: a Gmail historyId, a cron
    # label, an approval id. Used to make a run legible on the Activity screen.
    trigger_ref: Mapped[str | None] = mapped_column(String(255))

    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    token_cost: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    iterations: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error: Mapped[str | None] = mapped_column(Text)
    summary: Mapped[str | None] = mapped_column(Text)

    tool_calls: Mapped[list[ToolCall]] = relationship(
        back_populates="run", cascade="all, delete-orphan", order_by="ToolCall.sequence"
    )


class ToolCall(Base, CreatedAtMixin):
    """Append-only audit of every tool invocation. Never updated, never deleted."""

    __tablename__ = "tool_calls"
    __table_args__ = (
        UniqueConstraint("run_id", "sequence"),
        Index("ix_tool_calls_tool_name", "tool_name"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("runs.id", ondelete="CASCADE"), nullable=False
    )
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    tool_name: Mapped[str] = mapped_column(String(100), nullable=False)
    arguments: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    result: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    error: Mapped[str | None] = mapped_column(Text)
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    token_cost: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    skill_version_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("skill_versions.id", ondelete="SET NULL")
    )
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    run: Mapped[Run] = relationship(back_populates="tool_calls")


# ---------------------------------------------------------------------------
# Domain data
# ---------------------------------------------------------------------------


class Email(Base, TimestampMixin):
    """A Gmail message we have seen, plus the classification we gave it.

    Unique on `(user_id, gmail_message_id)`: Pub/Sub delivers at least once, and
    a re-sync after an expired historyId re-walks messages we already have.
    """

    __tablename__ = "emails"
    __table_args__ = (
        UniqueConstraint("user_id", "gmail_message_id"),
        Index("ix_emails_user_received", "user_id", "received_at"),
        Index("ix_emails_category", "category"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    gmail_message_id: Mapped[str] = mapped_column(String(64), nullable=False)
    gmail_thread_id: Mapped[str | None] = mapped_column(String(64))
    history_id: Mapped[int | None] = mapped_column(BigInteger)

    from_address: Mapped[str | None] = mapped_column(String(320))
    from_name: Mapped[str | None] = mapped_column(String(200))
    subject: Mapped[str | None] = mapped_column(Text)
    snippet: Mapped[str | None] = mapped_column(Text)
    received_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # Classification output. Nullable until the agent has processed the message.
    category: Mapped[enums.EmailCategory | None] = mapped_column(
        pg_enum(enums.EmailCategory, "email_category")
    )
    priority: Mapped[enums.Priority | None] = mapped_column(pg_enum(enums.Priority, "priority"))
    confidence: Mapped[float | None] = mapped_column(Numeric(4, 3))
    classification: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    run_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("runs.id", ondelete="SET NULL"))


class TenderSourceRow(Base, TimestampMixin):
    """A site we scrape, and how healthy that adapter currently is."""

    __tablename__ = "tender_sources"

    id: Mapped[uuid.UUID] = uuid_pk()
    key: Mapped[str] = mapped_column(String(50), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    base_url: Mapped[str] = mapped_column(String(500), nullable=False)
    adapter: Mapped[str] = mapped_column(String(100), nullable=False)
    is_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    #: The page the tender listing is actually on. `base_url` is the site root;
    #: these sites bury the listing several levels down and move it on redesign.
    listing_url: Mapped[str | None] = mapped_column(String(500))
    #: Tried in order when the primary 404s, because they do move.
    fallback_urls: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False, default=list)
    #: Sites the client added themselves, as opposed to the five we shipped.
    is_custom: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    entity: Mapped[str | None] = mapped_column(String(300))

    health: Mapped[enums.SourceHealth] = mapped_column(
        pg_enum(enums.SourceHealth, "source_health"),
        nullable=False,
        default=enums.SourceHealth.ok,
    )
    last_ok_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)
    consecutive_failures: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class Tender(Base, TimestampMixin):
    """A tender opportunity.

    Dedupe is two-tier because not every source publishes a reference number:
    `(source, reference_no)` when there is one, `(source, content_hash)` when
    there is not. Both are partial unique indexes, so a null reference number
    never collides with another null.
    """

    __tablename__ = "tenders"
    __table_args__ = (
        Index(
            "uq_tenders_source_reference_no",
            "source",
            "reference_no",
            unique=True,
            postgresql_where=text("reference_no IS NOT NULL"),
        ),
        Index(
            "uq_tenders_source_content_hash",
            "source",
            "content_hash",
            unique=True,
            postgresql_where=text("reference_no IS NULL"),
        ),
        Index("ix_tenders_closing_date", "closing_date"),
        Index("ix_tenders_first_seen_at", "first_seen_at"),
        CheckConstraint(
            "reference_no IS NOT NULL OR content_hash IS NOT NULL",
            name="reference_or_hash_present",
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    source: Mapped[str] = mapped_column(String(50), nullable=False)
    reference_no: Mapped[str | None] = mapped_column(String(200))
    # sha256 of the normalised title+entity+closing_date, for sources with no ref.
    content_hash: Mapped[str | None] = mapped_column(String(64))

    title: Mapped[str] = mapped_column(Text, nullable=False)
    entity: Mapped[str | None] = mapped_column(String(300))
    category: Mapped[str | None] = mapped_column(String(200))
    closing_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    estimated_value: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    currency: Mapped[str | None] = mapped_column(String(3))
    source_url: Mapped[str] = mapped_column(Text, nullable=False)
    county: Mapped[str | None] = mapped_column(String(100))

    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    first_seen_run_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("runs.id", ondelete="SET NULL")
    )
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    relevance_score: Mapped[float | None] = mapped_column(Numeric(4, 3))
    relevance_reason: Mapped[str | None] = mapped_column(Text)


# ---------------------------------------------------------------------------
# Approvals and delivery
# ---------------------------------------------------------------------------


class Approval(Base, TimestampMixin):
    """A proposed CRM write, awaiting a human.

    Nothing reaches Zoho without a row here moving to `approved`. The payload is
    stored exactly as proposed so that what is executed is what was reviewed.
    """

    __tablename__ = "approvals"
    __table_args__ = (
        Index("ix_approvals_user_status", "user_id", "status"),
        Index("ix_approvals_expires_at", "expires_at"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    run_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("runs.id", ondelete="SET NULL"))

    module: Mapped[str] = mapped_column(String(50), nullable=False)
    operation: Mapped[str] = mapped_column(String(20), nullable=False)  # create | update | note
    record_id: Mapped[str | None] = mapped_column(String(64))  # null for create

    proposed_payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    diff: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    rationale: Mapped[str | None] = mapped_column(Text)

    status: Mapped[enums.ApprovalStatus] = mapped_column(
        pg_enum(enums.ApprovalStatus, "approval_status"),
        nullable=False,
        default=enums.ApprovalStatus.pending,
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    approved_by: Mapped[str | None] = mapped_column(String(200))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    executed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    execution_result: Mapped[dict[str, Any] | None] = mapped_column(JSONB)


class Notification(Base, CreatedAtMixin):
    """Every delivery attempt, whatever the channel and whatever the outcome.

    `dedupe_key` is what stops a retried run from sending the same WhatsApp
    alert twice.
    """

    __tablename__ = "notifications"
    __table_args__ = (
        UniqueConstraint("dedupe_key"),
        Index("ix_notifications_user_created", "user_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    run_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("runs.id", ondelete="SET NULL"))

    channel: Mapped[enums.NotificationChannel] = mapped_column(
        pg_enum(enums.NotificationChannel, "notification_channel"), nullable=False
    )
    kind: Mapped[str] = mapped_column(String(64), nullable=False)
    target: Mapped[str | None] = mapped_column(String(320))
    dedupe_key: Mapped[str | None] = mapped_column(String(200))

    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    status: Mapped[enums.NotificationStatus] = mapped_column(
        pg_enum(enums.NotificationStatus, "notification_status"),
        nullable=False,
        default=enums.NotificationStatus.pending,
    )
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error: Mapped[str | None] = mapped_column(Text)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Feedback(Base, CreatedAtMixin):
    """A thumb up or down on a classification. One per subject per user.

    These become the labelled test cases the eval harness runs on, which is why
    the reason is kept.
    """

    __tablename__ = "feedback"
    __table_args__ = (UniqueConstraint("user_id", "subject_type", "subject_id"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    subject_type: Mapped[str] = mapped_column(String(20), nullable=False)  # email | tender
    subject_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    rating: Mapped[enums.FeedbackRating] = mapped_column(
        pg_enum(enums.FeedbackRating, "feedback_rating"), nullable=False
    )
    reason: Mapped[str | None] = mapped_column(Text)
    skill_version_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("skill_versions.id", ondelete="SET NULL")
    )


# ---------------------------------------------------------------------------
# Memory
# ---------------------------------------------------------------------------


class Memory(Base, TimestampMixin):
    """A memory row.

    `trust_tag` travels with the content forever. Anything tagged
    `untrusted_external` is rendered as quoted data and never occupies the
    system-prompt position, no matter which layer it belongs to.
    """

    __tablename__ = "memories"
    __table_args__ = (
        Index("ix_memories_user_layer", "user_id", "layer"),
        Index("ix_memories_trust_tag", "trust_tag"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    layer: Mapped[enums.MemoryLayer] = mapped_column(
        pg_enum(enums.MemoryLayer, "memory_layer"), nullable=False
    )
    trust_tag: Mapped[enums.TrustTag] = mapped_column(
        pg_enum(enums.TrustTag, "trust_tag"), nullable=False
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    source_ref: Mapped[str | None] = mapped_column(String(500))
    qdrant_point_id: Mapped[uuid.UUID | None] = mapped_column()
    attributes: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


__all__ = [
    "Approval",
    "Base",
    "Connection",
    "Email",
    "Feedback",
    "GmailSyncState",
    "Memory",
    "Notification",
    "PairingCode",
    "Run",
    "SkillVersion",
    "Tender",
    "TenderSourceRow",
    "ToolCall",
    "User",
    "WhatsAppLink",
]
