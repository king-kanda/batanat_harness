"""Placeholder tools.

Phase 3 builds the harness, not the integrations. Every tool the capability
table references is registered here with its real name, real argument schema and
a handler that refuses to pretend — so the machinery (binding, audit, limits,
circuit breaker) can be proven end to end before a single external API is wired.

Phase 4 replaces these handlers. The names and schemas are meant to survive
that, so the capability table does not move.

Two of them are real: `echo_fact` and `count_words` do exactly what they say,
and exist so tests can drive the loop without stubbing anything.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field

from batanat_api.agent.tools.registry import ToolContext, ToolSpec, register


class NotYetImplementedError(RuntimeError):
    """Raised by a placeholder handler. Recorded in the audit log like any failure."""


def _pending(name: str, phase: int):
    async def handler(context: ToolContext, args: BaseModel) -> dict[str, Any]:
        raise NotYetImplementedError(f"{name} is wired up in phase {phase}.")

    return handler


# --- real tools, used to exercise the loop -----------------------------------


class EchoFactArgs(BaseModel):
    fact: str = Field(description="A short statement to record.")


async def _echo_fact(context: ToolContext, args: EchoFactArgs) -> dict[str, Any]:
    return {"recorded": args.fact, "at": datetime.now(UTC).isoformat()}


class CountWordsArgs(BaseModel):
    text: str = Field(description="Text to count the words of.")


async def _count_words(context: ToolContext, args: CountWordsArgs) -> dict[str, Any]:
    return {"words": len(args.text.split())}


register(
    ToolSpec(
        name="echo_fact",
        description="Record a short fact and return it with a timestamp.",
        args_model=EchoFactArgs,
        handler=_echo_fact,
    )
)
register(
    ToolSpec(
        name="count_words",
        description="Count the words in a piece of text.",
        args_model=CountWordsArgs,
        handler=_count_words,
    )
)


# --- email -------------------------------------------------------------------


class ReadEmailArgs(BaseModel):
    since: str | None = Field(default=None, description="ISO timestamp lower bound.")
    limit: int = Field(default=20, ge=1, le=100)


class ClassifyEmailArgs(BaseModel):
    email_id: str = Field(description="Id of an email already read in this run.")


# --- tenders -----------------------------------------------------------------


class ScrapeTendersArgs(BaseModel):
    sources: list[str] = Field(
        default_factory=list, description="Source keys; empty means every enabled source."
    )
    lookback_hours: int = Field(default=24, ge=1, le=720)


class WebSearchArgs(BaseModel):
    query: str = Field(description="Search query.")
    max_results: int = Field(default=5, ge=1, le=20)


# --- CRM ---------------------------------------------------------------------


class CrmReadArgs(BaseModel):
    module: str = Field(description="Leads, Contacts or Deals.")
    criteria: str | None = Field(default=None, description="COQL criteria expression.")


class ProposeCrmEntryArgs(BaseModel):
    module: str = Field(description="Leads or Notes.")
    payload: dict[str, Any] = Field(description="Field values to write.")
    rationale: str = Field(description="Why this write is being proposed.")


class CommitCrmWriteArgs(BaseModel):
    approval_id: str = Field(description="Id of an approval a human has approved.")


class ApprovePendingArgs(BaseModel):
    approval_id: str = Field(description="Id of the approval to approve.")


class MaintenanceArgs(BaseModel):
    task: str = Field(description="Which maintenance task to run.")


for spec in [
    ToolSpec(
        name="read_email",
        description="Read recent emails from the connected Gmail account.",
        args_model=ReadEmailArgs,
        handler=_pending("read_email", 4),
    ),
    ToolSpec(
        name="classify_email",
        description="Classify an email against the active operating criteria.",
        args_model=ClassifyEmailArgs,
        handler=_pending("classify_email", 4),
    ),
    ToolSpec(
        name="scrape_tenders",
        description="Fetch current tender listings from the configured sources.",
        args_model=ScrapeTendersArgs,
        handler=_pending("scrape_tenders", 4),
    ),
    ToolSpec(
        name="web_search",
        description="Search the web for tender notices that the scrapers missed.",
        args_model=WebSearchArgs,
        handler=_pending("web_search", 4),
    ),
    ToolSpec(
        name="crm_read",
        description="Search or fetch records from Zoho CRM. Read-only.",
        args_model=CrmReadArgs,
        handler=_pending("crm_read", 4),
    ),
    ToolSpec(
        name="propose_crm_entry",
        description=(
            "Propose a CRM write for human approval. This does NOT write to the CRM; "
            "it queues a proposal and returns an approval id."
        ),
        args_model=ProposeCrmEntryArgs,
        handler=_pending("propose_crm_entry", 4),
    ),
    ToolSpec(
        name="commit_crm_write",
        description="Execute a CRM write that a human has already approved.",
        args_model=CommitCrmWriteArgs,
        handler=_pending("commit_crm_write", 4),
        is_write=True,
    ),
    ToolSpec(
        name="approve_pending",
        description="Approve a queued CRM proposal on the user's behalf.",
        args_model=ApprovePendingArgs,
        handler=_pending("approve_pending", 6),
        is_write=True,
    ),
    ToolSpec(
        name="internal_maintenance",
        description="Run an internal maintenance task.",
        args_model=MaintenanceArgs,
        handler=_pending("internal_maintenance", 5),
    ),
]:
    register(spec)
