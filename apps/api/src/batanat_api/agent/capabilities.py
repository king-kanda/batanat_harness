"""The capability resolver.

The security property the rest of the system rests on: **what a run may do is
decided by what triggered it, before the model is called.**

Enforcement is the tool schema, not a prompt instruction and not a check inside
the tool. `resolve_tools(gmail_push)` omits `commit_crm_write` entirely, so the
model is never told it exists. An injection cannot call a tool it has no name
for.

Keep `resolve_tools` a pure function over a table. The moment it needs a
database or a feature flag, it stops being something you can read and be
certain about.
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


# Every trigger in `TriggerType` must appear here — enforced by a test, so a
# new trigger cannot silently default to something permissive.
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
        # A human on a handset proven by the pairing flow, using WhatsApp as a
        # chat interface. Reads and proposes; cannot commit.
        #
        # `approve_pending` is deliberately absent, though the trust level would
        # permit it. Approving from WhatsApp still works — the webhook parses
        # `APPROVE n` with `approvals.parse_decision_reply` before the model is
        # ever called. Keeping the tool out of the schema means the difference
        # between "the handset can approve what we asked about" and "anything
        # that can talk to the model can talk it into a CRM write", and only the
        # first of those is a gate.
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

#: Triggers that carry a conversation, and may therefore be replayed prior
#: turns. Everything else runs blind by design: a pushed email or a scraped page
#: must never be handed what a trusted turn said, and the payload of both is
#: attacker-controlled. Asserted against the table by a test — a trigger cannot
#: appear here while its payload is untrusted.
CONVERSATIONAL_TRIGGERS = frozenset({TriggerType.web_chat, TriggerType.whatsapp_inbound})

#: Tools that must never exist. There is no delete path in this system.
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
    """Check the table against the registry at startup.

    Every trigger has a policy, every named tool exists, and no untrusted
    trigger holds a trusted-only tool. None of it is guaranteed by types.
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
