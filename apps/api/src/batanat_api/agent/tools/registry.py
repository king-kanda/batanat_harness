"""The tool registry.

A `ToolSpec` is the whole definition of a tool: its name, the description the
model reads, the Pydantic model describing its arguments, and the handler that
runs it. The registry is a plain dict, populated at import time.

Registration is deliberately separate from *binding*. A tool existing here does
not mean any run can call it — `agent.capabilities` decides that per trigger.
This module answers "what tools exist"; that one answers "which of them may
this run see".
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel


@dataclass(frozen=True, slots=True)
class ToolContext:
    """What a handler is allowed to know about the run it is part of."""

    run_id: Any
    user_id: Any
    trigger: Any
    trust: Any
    session: Any = None


ToolHandler = Callable[[ToolContext, BaseModel], Awaitable[dict[str, Any]]]


@dataclass(frozen=True, slots=True)
class ToolSpec:
    name: str
    description: str
    args_model: type[BaseModel]
    handler: ToolHandler
    #: Tools that change something outside this process. Used by the dry-run
    #: guard and surfaced in the Activity screen.
    is_write: bool = False

    def to_schema(self) -> dict[str, Any]:
        """The function definition handed to the model."""
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.args_model.model_json_schema(),
        }


_REGISTRY: dict[str, ToolSpec] = {}


def register(spec: ToolSpec) -> ToolSpec:
    if spec.name in _REGISTRY:
        raise ValueError(f"Tool {spec.name!r} is already registered.")
    _REGISTRY[spec.name] = spec
    return spec


def get_tool(name: str) -> ToolSpec:
    try:
        return _REGISTRY[name]
    except KeyError:
        raise KeyError(f"No tool named {name!r} is registered.") from None


def known_tool_names() -> frozenset[str]:
    return frozenset(_REGISTRY)


def all_tools() -> list[ToolSpec]:
    return list(_REGISTRY.values())


def clear_registry_for_tests() -> None:
    _REGISTRY.clear()
