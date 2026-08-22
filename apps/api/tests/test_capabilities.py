"""The capability resolver.

The central claim of this system is that an untrusted trigger cannot reach a
write tool, and that this is true because of the tool schema rather than
because of anything the model was asked to do. These tests are that claim,
written down. If one of them fails, the security model is gone, not degraded.
"""

from __future__ import annotations

import dataclasses

import pytest

from batanat_api.agent import capabilities
from batanat_api.agent.capabilities import (
    FORBIDDEN_TOOLS,
    POLICY,
    TRUSTED_ONLY_TOOLS,
    Capability,
    UnknownTriggerError,
    get_capability,
    resolve_tool_names,
    resolve_tools,
    trust_for,
    validate_policy,
)
from batanat_api.agent.tools import placeholders  # noqa: F401 — registers the tools
from batanat_api.agent.tools.registry import known_tool_names
from batanat_api.db.enums import TriggerType, TrustLevel

# The table from the PRD, restated independently. If the implementation and this
# disagree, one of them is wrong and a human needs to decide which.
EXPECTED = {
    TriggerType.gmail_push: (
        TrustLevel.untrusted,
        {"read_email", "classify_email", "propose_crm_entry"},
    ),
    TriggerType.cron_tender: (
        TrustLevel.untrusted,
        {"scrape_tenders", "web_search", "propose_crm_entry"},
    ),
    TriggerType.web_chat: (
        TrustLevel.trusted,
        {
            "read_email",
            "classify_email",
            "scrape_tenders",
            "web_search",
            "crm_read",
            "propose_crm_entry",
            "commit_crm_write",
        },
    ),
    TriggerType.whatsapp_inbound: (
        TrustLevel.trusted,
        {
            "read_email",
            "classify_email",
            "scrape_tenders",
            "web_search",
            "crm_read",
            "propose_crm_entry",
            "approve_pending",
        },
    ),
    TriggerType.approval_callback: (TrustLevel.system, set()),
    TriggerType.maintenance: (TrustLevel.system, {"internal_maintenance"}),
}


@pytest.mark.parametrize("trigger", list(TriggerType))
def test_every_trigger_resolves_to_the_specified_tools(trigger: TriggerType) -> None:
    expected_trust, expected_tools = EXPECTED[trigger]
    assert trust_for(trigger) is expected_trust
    assert set(resolve_tool_names(trigger)) == expected_tools


# --- the acceptance criterion ------------------------------------------------


def test_a_gmail_push_run_has_no_commit_tool_in_its_schema() -> None:
    """Not filtered, not refused at call time — absent from the schema entirely."""
    schemas = [tool.to_schema() for tool in resolve_tools(TriggerType.gmail_push)]
    serialised = str(schemas)

    assert "commit_crm_write" not in serialised
    assert "approve_pending" not in serialised
    assert "crm_read" not in serialised
    # And the tools it *does* have are the read/propose set.
    assert {s["name"] for s in schemas} == {
        "read_email",
        "classify_email",
        "propose_crm_entry",
    }


def test_a_tender_cron_run_has_no_commit_tool_in_its_schema() -> None:
    serialised = str([t.to_schema() for t in resolve_tools(TriggerType.cron_tender)])
    assert "commit_crm_write" not in serialised
    assert "approve_pending" not in serialised


@pytest.mark.parametrize("trigger", [TriggerType.gmail_push, TriggerType.cron_tender])
def test_untrusted_triggers_get_no_trusted_only_tool(trigger: TriggerType) -> None:
    assert not set(resolve_tool_names(trigger)) & TRUSTED_ONLY_TOOLS


def test_only_web_chat_can_commit_a_write() -> None:
    committers = {
        trigger for trigger in TriggerType if "commit_crm_write" in resolve_tool_names(trigger)
    }
    assert committers == {TriggerType.web_chat}


def test_whatsapp_can_approve_but_cannot_originate_a_write() -> None:
    """Trusted, but only enough to approve something a human already queued."""
    tools = set(resolve_tool_names(TriggerType.whatsapp_inbound))
    assert "approve_pending" in tools
    assert "commit_crm_write" not in tools


def test_approval_callback_uses_no_model_and_no_tools() -> None:
    capability = get_capability(TriggerType.approval_callback)
    assert capability.tools == ()
    assert capability.uses_llm is False


def test_untrusted_triggers_are_the_ones_carrying_outside_content() -> None:
    untrusted_payloads = {t for t, c in POLICY.items() if c.payload_is_untrusted}
    assert untrusted_payloads == {TriggerType.gmail_push, TriggerType.cron_tender}


# --- the table itself --------------------------------------------------------


def test_the_policy_covers_every_trigger() -> None:
    """A new trigger must be given a policy deliberately, not defaulted."""
    assert set(POLICY) == set(TriggerType)


def test_resolve_tools_is_pure() -> None:
    """Same input, same output, no state. It stays readable only if it stays pure."""
    first = resolve_tool_names(TriggerType.web_chat)
    second = resolve_tool_names(TriggerType.web_chat)
    assert first == second
    first.append("commit_crm_write")  # mutating the result must not affect the table
    assert resolve_tool_names(TriggerType.web_chat) == second


def test_the_policy_table_cannot_be_mutated_at_runtime() -> None:
    with pytest.raises(TypeError):
        POLICY[TriggerType.gmail_push] = Capability(  # type: ignore[index]
            trust=TrustLevel.trusted, tools=("commit_crm_write",), payload_is_untrusted=False
        )


def test_capabilities_are_frozen() -> None:
    with pytest.raises((AttributeError, TypeError, dataclasses.FrozenInstanceError)):
        get_capability(TriggerType.gmail_push).tools = ("commit_crm_write",)  # type: ignore[misc]


def test_an_unknown_trigger_raises_rather_than_defaulting() -> None:
    with pytest.raises(UnknownTriggerError):
        get_capability("not_a_trigger")  # type: ignore[arg-type]


def test_no_delete_tool_exists_anywhere() -> None:
    assert not known_tool_names() & FORBIDDEN_TOOLS
    assert not any("delete" in name.lower() for name in known_tool_names())


def test_validate_policy_passes_for_the_shipped_table() -> None:
    validate_policy()


def test_validate_policy_catches_a_leaked_write_tool(monkeypatch: pytest.MonkeyPatch) -> None:
    """The guard that would catch a careless edit to POLICY."""
    from types import MappingProxyType

    broken = dict(POLICY)
    broken[TriggerType.gmail_push] = Capability(
        trust=TrustLevel.untrusted,
        tools=("read_email", "commit_crm_write"),
        payload_is_untrusted=True,
    )
    monkeypatch.setattr(capabilities, "POLICY", MappingProxyType(broken))

    with pytest.raises(RuntimeError, match="trusted-only tools"):
        validate_policy()


def test_validate_policy_catches_a_missing_trigger(monkeypatch: pytest.MonkeyPatch) -> None:
    from types import MappingProxyType

    incomplete = {k: v for k, v in POLICY.items() if k is not TriggerType.maintenance}
    monkeypatch.setattr(capabilities, "POLICY", MappingProxyType(incomplete))

    with pytest.raises(RuntimeError, match="no capability policy"):
        validate_policy()


def test_validate_policy_catches_a_typo_in_a_tool_name(monkeypatch: pytest.MonkeyPatch) -> None:
    from types import MappingProxyType

    broken = dict(POLICY)
    broken[TriggerType.gmail_push] = Capability(
        trust=TrustLevel.untrusted, tools=("read_emails",), payload_is_untrusted=True
    )
    monkeypatch.setattr(capabilities, "POLICY", MappingProxyType(broken))

    with pytest.raises(RuntimeError, match="unknown tools"):
        validate_policy()


def test_the_policy_dump_is_readable() -> None:
    """The Activity screen shows this; it has to be honest and complete."""
    dump = capabilities.audit_policy()
    assert set(dump) == {t.value for t in TriggerType}
    assert dump["gmail_push"]["trust"] == "untrusted"
    assert "commit_crm_write" not in dump["gmail_push"]["tools"]
