"""Model clients.

`AnthropicModel` is the real one. `ScriptedModel` returns a fixed sequence of
turns and is what the tests drive the loop with — the harness has to be provable
without an API key, and phase 9's demo mode needs the same seam.

The runner depends on the `ModelClient` protocol, not on either of these.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from batanat_api.agent.runner import ModelResponse, ToolRequest
from batanat_api.config import get_settings
from batanat_api.core.logging import get_logger

log = get_logger(__name__)


class ModelNotConfiguredError(RuntimeError):
    pass


class AnthropicModel:
    """Claude, via the Anthropic SDK.

    Tools are passed as the request's `tools` parameter — this is the mechanism
    the whole capability model rests on. A tool absent from this list has no
    name the model can emit.
    """

    def __init__(self, model: str | None = None):
        settings = get_settings()
        self.model = model or settings.agent_model
        self._api_key = settings.anthropic_api_key

    def is_configured(self) -> bool:
        return bool(self._api_key)

    async def complete(
        self,
        *,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        timeout_s: float,
    ) -> ModelResponse:
        if not self._api_key:
            raise ModelNotConfiguredError("ANTHROPIC_API_KEY is not set — see TODO.md.")

        from anthropic import AsyncAnthropic

        client = AsyncAnthropic(api_key=self._api_key, timeout=max(5.0, timeout_s))
        response = await client.messages.create(
            model=self.model,
            max_tokens=4096,
            system=system,
            messages=_to_anthropic_messages(messages),
            tools=tools or [],
        )

        text_parts: list[str] = []
        tool_calls: list[ToolRequest] = []
        for block in response.content:
            if block.type == "text":
                text_parts.append(block.text)
            elif block.type == "tool_use":
                tool_calls.append(
                    ToolRequest(id=block.id, name=block.name, arguments=dict(block.input))
                )

        return ModelResponse(
            text="\n".join(text_parts) or None,
            tool_calls=tuple(tool_calls),
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
        )


def _to_anthropic_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Translate the runner's neutral message shape into Anthropic content blocks."""
    converted: list[dict[str, Any]] = []
    for message in messages:
        if message["role"] == "assistant" and message.get("tool_calls"):
            blocks: list[dict[str, Any]] = []
            if message.get("content"):
                blocks.append({"type": "text", "text": message["content"]})
            blocks.extend(
                {
                    "type": "tool_use",
                    "id": call["id"],
                    "name": call["name"],
                    "input": call["arguments"],
                }
                for call in message["tool_calls"]
            )
            converted.append({"role": "assistant", "content": blocks})
        elif message.get("tool_call_id"):
            converted.append(
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": message["tool_call_id"],
                            "content": message["content"],
                        }
                    ],
                }
            )
        else:
            converted.append({"role": message["role"], "content": message["content"]})
    return converted


class ScriptedModel:
    """Replays a fixed list of turns. Records what it was asked, for assertions."""

    def __init__(self, turns: Iterable[ModelResponse]):
        self._turns = list(turns)
        self.calls: list[dict[str, Any]] = []

    async def complete(
        self,
        *,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        timeout_s: float,
    ) -> ModelResponse:
        self.calls.append({"system": system, "messages": list(messages), "tools": tools})
        if not self._turns:
            return ModelResponse(text="done", input_tokens=1, output_tokens=1)
        return self._turns.pop(0)

    @property
    def last_system_prompt(self) -> str:
        return self.calls[-1]["system"]

    @property
    def tool_names_offered(self) -> list[str]:
        return [tool["name"] for tool in self.calls[-1]["tools"]]


class LoopingModel:
    """Always asks for the same tool. Used to prove the limits actually stop a run."""

    def __init__(self, tool_name: str = "echo_fact", tokens_per_turn: int = 10):
        self.tool_name = tool_name
        self.tokens_per_turn = tokens_per_turn
        self.turns = 0

    async def complete(self, **_: Any) -> ModelResponse:
        self.turns += 1
        return ModelResponse(
            text="thinking",
            tool_calls=(
                ToolRequest(
                    id=f"call-{self.turns}",
                    name=self.tool_name,
                    arguments={"fact": f"iteration {self.turns}"},
                ),
            ),
            input_tokens=self.tokens_per_turn,
            output_tokens=self.tokens_per_turn,
        )
