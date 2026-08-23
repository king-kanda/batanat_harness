"""Model providers.

The runner depends on the `ModelClient` protocol, never on a vendor. This module
holds the implementations and the factory that picks one from `LLM_PROVIDER`.

Three are supported and two of them share an implementation: **Groq** and
**OpenRouter** both speak the OpenAI chat-completions API, so one client covers
both and differs only in base URL, key and default model. **Anthropic** has its
own message shape and lives in `agent.model`.

Written against the HTTP APIs with `httpx` rather than pulling the `openai` SDK,
because the only thing needed is one POST and a response parse, and the SDK
would be a dependency carrying a lot of surface we do not use.

**The important detail is tool translation.** The whole security model rests on
the tool schema handed to the model: a tool absent from that list has no name to
call. Anthropic and OpenAI describe tools differently, so `to_openai_tools()`
translates the schema — and translates it *faithfully*, because a tool that
survives translation when it should not have would silently widen what a run can
do. The capability resolver still decides which tools are in the list; this only
changes how they are written down.
"""

from __future__ import annotations

import json
from typing import Any

import httpx

from batanat_api.agent.runner import ModelResponse, ToolRequest
from batanat_api.config import get_settings
from batanat_api.core.logging import get_logger

log = get_logger(__name__)


class ModelNotConfiguredError(RuntimeError):
    """No API key for the selected provider."""


class ModelCallError(RuntimeError):
    """The provider rejected the request or returned something unusable."""


#: base URL, env var holding the key, and a sensible open-weights default.
PROVIDERS: dict[str, dict[str, str]] = {
    "groq": {
        "base_url": "https://api.groq.com/openai/v1",
        "key_setting": "groq_api_key",
        "default_model": "llama-3.3-70b-versatile",
        "label": "Groq",
    },
    "openrouter": {
        "base_url": "https://openrouter.ai/api/v1",
        "key_setting": "openrouter_api_key",
        "default_model": "meta-llama/llama-3.3-70b-instruct",
        "label": "OpenRouter",
    },
}


def to_openai_tools(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Translate our tool schemas (Anthropic shape) into OpenAI's function shape.

    Anthropic: {name, description, input_schema}
    OpenAI:    {type: function, function: {name, description, parameters}}

    One-to-one, and nothing is added: the list that comes out has exactly the
    tools that went in.
    """
    return [
        {
            "type": "function",
            "function": {
                "name": tool["name"],
                "description": tool["description"],
                "parameters": tool.get("input_schema", {"type": "object", "properties": {}}),
            },
        }
        for tool in tools
    ]


def to_openai_messages(system: str, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Translate the runner's neutral message shape into OpenAI's.

    The system prompt becomes a `system` message. Tool results become `tool`
    messages keyed by `tool_call_id` — they must not be plain user messages, or
    the model loses the link between a call and its result.
    """
    converted: list[dict[str, Any]] = [{"role": "system", "content": system}]

    for message in messages:
        if message["role"] == "assistant" and message.get("tool_calls"):
            converted.append(
                {
                    "role": "assistant",
                    "content": message.get("content") or None,
                    "tool_calls": [
                        {
                            "id": call["id"],
                            "type": "function",
                            "function": {
                                "name": call["name"],
                                "arguments": json.dumps(call["arguments"]),
                            },
                        }
                        for call in message["tool_calls"]
                    ],
                }
            )
        elif message.get("tool_call_id"):
            converted.append(
                {
                    "role": "tool",
                    "tool_call_id": message["tool_call_id"],
                    "content": message["content"],
                }
            )
        else:
            converted.append({"role": message["role"], "content": message["content"]})

    return converted


class OpenAICompatibleModel:
    """Groq, OpenRouter, or anything else speaking OpenAI chat-completions."""

    def __init__(self, provider: str, *, model: str | None = None):
        if provider not in PROVIDERS:
            raise ValueError(
                f"Unknown provider {provider!r}. Known: {sorted(PROVIDERS)} (plus 'anthropic')."
            )
        self.provider = provider
        spec = PROVIDERS[provider]
        settings = get_settings()

        self.base_url = spec["base_url"]
        self.label = spec["label"]
        self._api_key = getattr(settings, spec["key_setting"], None)
        self.model = model or settings.agent_model or spec["default_model"]

    def is_configured(self) -> bool:
        return bool(self._api_key)

    def _headers(self) -> dict[str, str]:
        headers = {"Authorization": f"Bearer {self._api_key}"}
        if self.provider == "openrouter":
            # OpenRouter asks callers to identify themselves; it also improves
            # rate limits and shows up in their dashboard.
            settings = get_settings()
            headers["HTTP-Referer"] = settings.web_public_url
            headers["X-Title"] = "Batanat Harness"
        return headers

    async def complete(
        self,
        *,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        timeout_s: float,
    ) -> ModelResponse:
        if not self._api_key:
            raise ModelNotConfiguredError(
                f"{self.label} is selected but its API key is not set — see TODO.md."
            )

        payload: dict[str, Any] = {
            "model": self.model,
            "messages": to_openai_messages(system, messages),
            "max_tokens": 4096,
        }
        if tools:
            payload["tools"] = to_openai_tools(tools)
            payload["tool_choice"] = "auto"

        async with httpx.AsyncClient(timeout=max(10.0, timeout_s)) as client:
            response = await client.post(
                f"{self.base_url}/chat/completions", headers=self._headers(), json=payload
            )

        if not response.is_success:
            detail = response.text[:300]
            log.error(
                "model.call_failed",
                provider=self.provider,
                status_code=response.status_code,
                model=self.model,
            )
            raise ModelCallError(f"{self.label} returned {response.status_code}: {detail}")

        data = response.json()
        try:
            choice = data["choices"][0]["message"]
        except (KeyError, IndexError) as exc:
            raise ModelCallError(f"{self.label} returned no choices: {str(data)[:200]}") from exc

        tool_calls: list[ToolRequest] = []
        for call in choice.get("tool_calls") or []:
            function = call.get("function", {})
            raw_arguments = function.get("arguments") or "{}"
            try:
                arguments = json.loads(raw_arguments)
            except json.JSONDecodeError:
                # Smaller open models sometimes emit not-quite-JSON. Surface it
                # as a tool call with bad arguments rather than crashing the run
                # — the runner records the validation error and the model
                # retries, which is exactly the intended path.
                log.warning(
                    "model.bad_tool_arguments", provider=self.provider, tool=function.get("name")
                )
                arguments = {"__unparsed__": raw_arguments}

            tool_calls.append(
                ToolRequest(
                    id=call.get("id") or f"call-{len(tool_calls)}",
                    name=function.get("name", ""),
                    arguments=arguments if isinstance(arguments, dict) else {},
                )
            )

        usage = data.get("usage") or {}
        return ModelResponse(
            text=choice.get("content") or None,
            tool_calls=tuple(tool_calls),
            input_tokens=usage.get("prompt_tokens", 0),
            output_tokens=usage.get("completion_tokens", 0),
        )


def get_model():
    """Build the model client named by `LLM_PROVIDER`.

    Called wherever a run starts. Swapping providers is an env change; no code
    downstream knows which one is in use.
    """
    settings = get_settings()
    provider = (settings.llm_provider or "anthropic").lower()

    if provider == "anthropic":
        from batanat_api.agent.model import AnthropicModel

        return AnthropicModel()

    return OpenAICompatibleModel(provider)


def describe_model() -> dict[str, Any]:
    """What the Dashboard and the health page show about the model in use."""
    settings = get_settings()
    provider = (settings.llm_provider or "anthropic").lower()
    try:
        model = get_model()
        return {
            "provider": provider,
            "model": getattr(model, "model", settings.agent_model),
            "configured": model.is_configured(),
        }
    except ValueError as exc:
        return {"provider": provider, "model": None, "configured": False, "error": str(exc)}
