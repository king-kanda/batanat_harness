"""Enumerations shared by the ORM, the API contracts and the agent runtime.

These are stored as native Postgres enums. Adding a value later needs a
migration (`ALTER TYPE … ADD VALUE`), which is the point: the set of trust
levels and trigger types should not be extensible by accident.
"""

from __future__ import annotations

from enum import StrEnum


class Provider(StrEnum):
    gmail = "gmail"
    zoho = "zoho"
    whatsapp = "whatsapp"


class ConnectionStatus(StrEnum):
    connected = "connected"
    expired = "expired"  # refresh token gone; user must reconnect
    error = "error"  # last call failed; see last_error
    revoked = "revoked"  # disconnected by us or upstream


class TriggerType(StrEnum):
    gmail_push = "gmail_push"
    cron_tender = "cron_tender"
    web_chat = "web_chat"
    whatsapp_inbound = "whatsapp_inbound"
    approval_callback = "approval_callback"
    maintenance = "maintenance"


class TrustLevel(StrEnum):
    """Determines which tools a run is allowed to be handed.

    `untrusted` — the payload originates outside the system (an email body,
    a scraped page). Read tools and `propose_crm_entry` only.
    `trusted`   — the payload originates from an authenticated human.
    `system`    — internal machinery; usually no LLM at all.
    """

    untrusted = "untrusted"
    trusted = "trusted"
    system = "system"


class RunStatus(StrEnum):
    running = "running"
    succeeded = "succeeded"
    failed = "failed"
    refused = "refused"  # kill switch, or no tools bound
    limit_exceeded = "limit_exceeded"  # iterations, tokens or wall clock


class ApprovalStatus(StrEnum):
    pending = "pending"
    approved = "approved"
    rejected = "rejected"
    expired = "expired"
    executed = "executed"
    failed = "failed"


class NotificationChannel(StrEnum):
    whatsapp = "whatsapp"
    email = "email"
    web = "web"


class NotificationStatus(StrEnum):
    pending = "pending"
    sent = "sent"
    failed = "failed"
    suppressed = "suppressed"  # deliberately not sent (e.g. below threshold)


class MemoryLayer(StrEnum):
    procedural = "procedural"
    semantic = "semantic"
    episodic = "episodic"


class TrustTag(StrEnum):
    """Provenance of a memory row. Never render `untrusted_external` as instruction."""

    user_asserted = "user_asserted"
    system_derived = "system_derived"
    untrusted_external = "untrusted_external"


class EmailCategory(StrEnum):
    opportunity = "opportunity"
    client = "client"
    supplier = "supplier"
    administrative = "administrative"
    spam = "spam"
    not_relevant = "not_relevant"


class Priority(StrEnum):
    high = "high"
    medium = "medium"
    low = "low"


class FeedbackRating(StrEnum):
    up = "up"
    down = "down"


class SourceHealth(StrEnum):
    ok = "ok"
    degraded = "degraded"  # falling back to search
    failing = "failing"


class ChatRole(StrEnum):
    """Who authored a stored chat message.

    Only these two are persisted. Tool calls live in `tool_calls`, keyed to the
    run, and are replayed from there rather than stored twice.
    """

    user = "user"
    assistant = "assistant"
