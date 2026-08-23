"""Model providers: schema translation and response parsing.

The capability model rests on the tool list handed to the model, so translating
that list between vendor formats is security-relevant: a tool that appeared,
disappeared or changed shape in translation would change what a run can do.
"""

from __future__ import annotations

import pytest

from batanat_api.agent.providers import (
    PROVIDERS,
    OpenAICompatibleModel,
    to_openai_messages,
    to_openai_tools,
)
from batanat_api.config import get_settings

ANTHROPIC_TOOLS = [
    {
        "name": "read_email",
        "description": "Read recent emails.",
        "input_schema": {"type": "object", "properties": {"limit": {"type": "integer"}}},
    },
    {
        "name": "propose_crm_entry",
        "description": "Queue a CRM write for approval.",
        "input_schema": {"type": "object", "properties": {"module": {"type": "string"}}},
    },
]


def test_tool_translation_is_one_to_one() -> None:
    """Exactly the tools that went in come out — no more, no fewer."""
    translated = to_openai_tools(ANTHROPIC_TOOLS)
    assert [t["function"]["name"] for t in translated] == ["read_email", "propose_crm_entry"]


def test_translation_preserves_the_argument_schema() -> None:
    translated = to_openai_tools(ANTHROPIC_TOOLS)
    assert translated[0]["function"]["parameters"] == ANTHROPIC_TOOLS[0]["input_schema"]
    assert translated[0]["type"] == "function"


def test_an_empty_toolbelt_translates_to_an_empty_list() -> None:
    """A system trigger gets no tools; that must survive translation."""
    assert to_openai_tools([]) == []


def test_a_tool_with_no_schema_still_translates() -> None:
    translated = to_openai_tools([{"name": "ping", "description": "d"}])
    assert translated[0]["function"]["parameters"] == {"type": "object", "properties": {}}


def test_the_system_prompt_becomes_a_system_message() -> None:
    messages = to_openai_messages("SYSTEM RULES", [{"role": "user", "content": "hello"}])
    assert messages[0] == {"role": "system", "content": "SYSTEM RULES"}
    assert messages[1]["content"] == "hello"


def test_tool_results_become_tool_messages_not_user_messages() -> None:
    """As a user message the model loses the link between a call and its result."""
    messages = to_openai_messages(
        "sys",
        [
            {"role": "user", "content": "go"},
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [{"id": "c1", "name": "read_email", "arguments": {"limit": 5}}],
            },
            {"role": "user", "content": "3 emails", "tool_call_id": "c1"},
        ],
    )

    assistant = messages[2]
    assert assistant["tool_calls"][0]["function"]["name"] == "read_email"
    # Arguments are a JSON *string* in the OpenAI format, not an object.
    assert assistant["tool_calls"][0]["function"]["arguments"] == '{"limit": 5}'

    result = messages[3]
    assert result["role"] == "tool"
    assert result["tool_call_id"] == "c1"


@pytest.mark.parametrize("provider", sorted(PROVIDERS))
def test_each_provider_has_a_base_url_and_a_default_model(provider: str) -> None:
    spec = PROVIDERS[provider]
    assert spec["base_url"].startswith("https://")
    assert spec["default_model"]


def test_an_unknown_provider_is_refused() -> None:
    with pytest.raises(ValueError, match="Unknown provider"):
        OpenAICompatibleModel("not-a-provider")


def test_a_provider_without_a_key_reports_itself_unconfigured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(get_settings(), "groq_api_key", None)
    assert OpenAICompatibleModel("groq").is_configured() is False


def test_a_configured_provider_uses_its_default_model(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "groq_api_key", "test-key")
    monkeypatch.setattr(get_settings(), "agent_model", "")
    model = OpenAICompatibleModel("groq")
    assert model.is_configured() is True
    assert model.model == PROVIDERS["groq"]["default_model"]


def test_an_explicit_model_overrides_the_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "groq_api_key", "test-key")
    monkeypatch.setattr(get_settings(), "agent_model", "llama-3.1-8b-instant")
    assert OpenAICompatibleModel("groq").model == "llama-3.1-8b-instant"


def test_openrouter_identifies_itself(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "openrouter_api_key", "test-key")
    headers = OpenAICompatibleModel("openrouter")._headers()
    assert headers["Authorization"] == "Bearer test-key"
    assert "X-Title" in headers


def test_the_factory_follows_the_env_setting(monkeypatch: pytest.MonkeyPatch) -> None:
    from batanat_api.agent.providers import get_model

    monkeypatch.setattr(get_settings(), "llm_provider", "openrouter")
    assert isinstance(get_model(), OpenAICompatibleModel)

    monkeypatch.setattr(get_settings(), "llm_provider", "anthropic")
    from batanat_api.agent.model import AnthropicModel

    assert isinstance(get_model(), AnthropicModel)
