"""The capability resolver.

This is the security property the rest of the system is built on: **what a run
is allowed to do is decided by what triggered it, before the model is called.**

A Gmail push is caused by an email — content written by a stranger. A tender
cron is caused by a scraped page — content written by a stranger. Neither can
be allowed to reach a tool that writes to the CRM, because the instruction to
do so could have come from the stranger.

The enforcement is not a prompt instruction, and not a check inside the tool. It
is the tool schema itself: `resolve_tools(gmail_push)` returns a list that does
not contain `commit_crm_write`, so the model is never told that tool exists and
has no name to call. A prompt injection cannot invoke a tool that is absent from
its function definitions.

`resolve_tools` is a pure function over a table. Keep it that way — the moment
it needs a database, a request context, or a feature flag, it stops being
something you can read and be certain about.
"""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType

from batanat_api.agent.tools.registry import ToolSpec, get_tool, known_tool_names
from batanat_api.db.enums import TriggerType, TrustLevel


@dataclass(frozen=True, slots=True)
class Capability:
    """What one trigger is permitted to do."""

    trust: TrustLevel
    tools: tuple[str, ...]
    #: True when the trigger's payload is authored outside the system and must
    #: therefore be rendered as quoted data, never as instruction.
    payload_is_untrusted: bool
    #: True when the trigger runs without a language model at all.
    uses_llm: bool = True


# The table. Every trigger in `TriggerType` must appear here — a test enforces
# that, so adding a trigger without deciding its capabilities fails the build
# rather than silently defaulting to something permissive.
POLICY: MappingProxyType[TriggerType, Capability] = MappingProxyType(
    {
        # An email body is attacker-controlled text. Read and propose only.
        TriggerType.gmail_push: Capability(
            trust=TrustLevel.untrusted,
            tools=("read_email", "read_thread", "classify_email", "propose_crm_entry"),
            payload_is_untrusted=True,
        ),
        # Scraped HTML is attacker-controlled text, for the same reason.
        TriggerType.cron_tender: Capability(
            trust=TrustLevel.untrusted,
            tools=("scrape_tenders", "web_search", "propose_crm_entry"),
            payload_is_untrusted=True,
        ),
        # A human typed this, in a session we authenticated.
        TriggerType.web_chat: Capability(
            trust=TrustLevel.trusted,
            tools=(
                "read_email",
                "read_thread",
                "classify_email",
                "scrape_tenders",
                "web_search",
                "crm_read",
                "propose_crm_entry",
                "commit_crm_write",
            ),
            payload_is_untrusted=False,
        ),
        # A human, on a handset proven by the pairing flow. Trusted enough to
        # approve something already queued; never to originate a write.
        #
        # Read this before wiring the trigger: `approve_pending` executes the
        # CRM write immediately, so once inbound WhatsApp reaches the runner,
        # the strength of the approval gate is exactly the strength of phone
        # number pairing — and `payload_is_untrusted=False` puts the message
        # body in the instruction position. Constrain the body through
        # `approvals.service.parse_decision_reply` rather than handing it to the
        # model as free text; that parser exists for this reason and accepts
        # nothing but APPROVE/REJECT plus an index. The webhook currently
        # acknowledges and stops, so none of this is live yet.
        TriggerType.whatsapp_inbound: Capability(
            trust=TrustLevel.trusted,
            tools=(
                "read_email",
                "read_thread",
                "classify_email",
                "scrape_tenders",
                "web_search",
                "crm_read",
                "propose_crm_entry",
                "approve_pending",
            ),
            payload_is_untrusted=False,
        ),
        # Executing an approved write. No model, no tools — the payload was
        # already reviewed by a human, so there is nothing left to decide.
        TriggerType.approval_callback: Capability(
            trust=TrustLevel.system,
            tools=(),
            payload_is_untrusted=False,
            uses_llm=False,
        ),
        # Housekeeping: watch renewal, token sweeps, health checks.
        TriggerType.maintenance: Capability(
            trust=TrustLevel.system,
            tools=("internal_maintenance",),
            payload_is_untrusted=False,
            uses_llm=False,
        ),
    }
)

#: Tools that may only ever be bound to a trusted trigger. Asserted against the
#: table by a test, so a careless edit to POLICY fails rather than ships.
TRUSTED_ONLY_TOOLS = frozenset({"commit_crm_write", "approve_pending", "crm_read"})

#: Tools that must never exist at all. There is no delete path in this system;
#: if one of these ever appears in the registry, that is a bug, not a feature.
FORBIDDEN_TOOLS = frozenset({"crm_delete", "delete_record", "purge"})


class UnknownTriggerError(KeyError):
    pass


def get_capability(trigger: TriggerType) -> Capability:
    try:
        return POLICY[trigger]
    except KeyError:
        raise UnknownTriggerError(
            f"No capability policy for trigger {trigger!r}. Add it to POLICY explicitly — "
            "there is deliberately no default."
        ) from None


def resolve_tools(trigger: TriggerType) -> list[ToolSpec]:
    """The tools a run from this trigger may be handed. Pure; no side effects."""
    return [get_tool(name) for name in get_capability(trigger).tools]


def resolve_tool_names(trigger: TriggerType) -> list[str]:
    return list(get_capability(trigger).tools)


def trust_for(trigger: TriggerType) -> TrustLevel:
    return get_capability(trigger).trust


def audit_policy() -> dict[str, dict[str, object]]:
    """A readable dump of the whole table, for the Activity screen and docs."""
    return {
        trigger.value: {
            "trust": capability.trust.value,
            "tools": list(capability.tools),
            "payload_is_untrusted": capability.payload_is_untrusted,
            "uses_llm": capability.uses_llm,
        }
        for trigger, capability in POLICY.items()
    }


def validate_policy() -> None:
    """Check the table against the registry. Called at startup — fail fast.

    Three things must hold, and none of them are guaranteed by types alone:
    every trigger has a policy, every named tool exists, and no untrusted
    trigger has been handed a trusted-only tool.
    """
    missing = [t.value for t in TriggerType if t not in POLICY]
    if missing:
        raise RuntimeError(f"Triggers with no capability policy: {missing}")

    registry = known_tool_names()

    for trigger, capability in POLICY.items():
        unknown = [name for name in capability.tools if name not in registry]
        if unknown:
            raise RuntimeError(f"{trigger.value} references unknown tools: {unknown}")

        if capability.trust is not TrustLevel.trusted:
            leaked = sorted(set(capability.tools) & TRUSTED_ONLY_TOOLS)
            if leaked:
                raise RuntimeError(
                    f"{trigger.value} is {capability.trust.value} but was given "
                    f"trusted-only tools: {leaked}"
                )

    forbidden = sorted(registry & FORBIDDEN_TOOLS)
    if forbidden:
        raise RuntimeError(f"Forbidden tools exist in the registry: {forbidden}")
