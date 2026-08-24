"""The agent loop.

Order of operations, and none of it is negotiable:

1. **Kill switch** — checked before anything else, including before the run row
   is created. One environment variable stops every run in the system.
2. **Capability resolution** — the tool schema is fixed here, from the trigger
   alone, before the model is involved.
3. **Run row** — written with `bound_tools` *before* the first model call, so
   the audit trail exists even if the process dies mid-run.
4. **Loop** — every iteration checks the budget first; every tool call is
   checked against the circuit breaker, timed, and appended to `tool_calls`.

Each tool runs inside its own savepoint. A tool that fails against the database
would otherwise leave the transaction aborted, which means the `ToolCall` row
recording that failure cannot be written either — losing the audit trail in
exactly the case you most want it.

The model is injected rather than constructed here. That is what makes the loop
testable without an API key, and it is also how demo mode will work in phase 9.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Protocol

from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from batanat_api.agent import capabilities, checkpoint, prompt
from batanat_api.agent.limits import (
    CircuitBreaker,
    CircuitOpenError,
    LimitExceeded,
    RunBudget,
    RunLimits,
)
from batanat_api.agent.tools.registry import ToolContext, ToolSpec
from batanat_api.config import get_settings
from batanat_api.core.logging import get_logger
from batanat_api.core.run_context import run_context
from batanat_api.db import enums
from batanat_api.db.models import Run, ToolCall

log = get_logger(__name__)


class KillSwitchEngagedError(RuntimeError):
    """KILL_SWITCH is on. No run may start."""


# --- the model interface -----------------------------------------------------


@dataclass(frozen=True, slots=True)
class ToolRequest:
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass(frozen=True, slots=True)
class ModelResponse:
    """What one model turn produced: some text, and/or some tool calls."""

    text: str | None = None
    tool_calls: tuple[ToolRequest, ...] = ()
    input_tokens: int = 0
    output_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens


class ModelClient(Protocol):
    """Anything that can take messages plus tool schemas and return a turn."""

    async def complete(
        self,
        *,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        timeout_s: float,
    ) -> ModelResponse: ...


# --- result ------------------------------------------------------------------


@dataclass
class RunResult:
    run_id: uuid.UUID
    status: enums.RunStatus
    output: str | None
    bound_tools: list[str]
    iterations: int
    token_cost: int
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    error: str | None = None


# --- the loop ----------------------------------------------------------------


class AgentRunner:
    def __init__(
        self,
        *,
        model: ModelClient,
        limits: RunLimits | None = None,
        breaker: CircuitBreaker | None = None,
    ):
        self.model = model
        self.limits = limits or RunLimits.from_settings()
        self.breaker = breaker or CircuitBreaker()

    async def run(
        self,
        session: AsyncSession,
        *,
        user_id: uuid.UUID,
        trigger: enums.TriggerType,
        payload: Any = None,
        instruction: str | None = None,
        skill_content: str | None = None,
        skill_version_id: uuid.UUID | None = None,
        memories: list[str] | None = None,
        quoted_context: list[str] | None = None,
        trigger_ref: str | None = None,
        history: list[dict[str, Any]] | None = None,
    ) -> RunResult:
        settings = get_settings()

        # 1. Kill switch, before anything is created or spent.
        if settings.kill_switch:
            log.warning("agent.run.refused", reason="kill_switch", trigger=trigger.value)
            raise KillSwitchEngagedError(
                "KILL_SWITCH is engaged; no agent runs will start. Unset it in .env."
            )

        # 2. Capabilities, from the trigger alone.
        capability = capabilities.get_capability(trigger)

        # Conversation history belongs to conversational triggers and nowhere
        # else. An untrusted trigger — a pushed email, a scraped page — must not
        # be handed what a trusted turn said, so this is dropped here rather
        # than trusted to every call site to get right.
        if history and trigger not in capabilities.CONVERSATIONAL_TRIGGERS:
            log.warning("agent.history_discarded", trigger=trigger.value, messages=len(history))
            history = None

        tools = capabilities.resolve_tools(trigger)
        tool_map = {tool.name: tool for tool in tools}
        tool_names = [tool.name for tool in tools]

        # 3. The run row, before the first model call.
        run = Run(
            user_id=user_id,
            trigger_type=trigger,
            trust_level=capability.trust,
            bound_tools=tool_names,
            status=enums.RunStatus.running,
            skill_version_id=skill_version_id,
            trigger_ref=trigger_ref,
            started_at=datetime.now(UTC),
        )
        session.add(run)
        await session.flush()

        with run_context(run.id.hex):
            log.info(
                "agent.run.start",
                trigger=trigger.value,
                trust=capability.trust.value,
                bound_tools=tool_names,
            )

            if not capability.uses_llm:
                # approval_callback and maintenance execute directly. There is
                # nothing for a model to decide, so we do not call one.
                return await self._finish(
                    session, run, enums.RunStatus.succeeded, output=None, budget=None
                )

            budget = RunBudget(self.limits)
            system = prompt.build_system_prompt(
                skill_content=skill_content,
                trust=capability.trust,
                tool_names=tool_names,
                memories=memories,
                trigger=trigger,
            )
            # Prior turns first, then this one. Only chat supplies history —
            # a Gmail push or a cron sweep has no thread, and giving one a
            # conversation would let an untrusted trigger read what a trusted
            # turn said.
            messages: list[dict[str, Any]] = list(history or [])
            messages.append(
                {
                    "role": "user",
                    "content": prompt.build_trigger_message(
                        trigger=trigger,
                        payload=payload,
                        payload_is_untrusted=capability.payload_is_untrusted,
                        instruction=instruction,
                        quoted_context=quoted_context,
                    ),
                }
            )

            recorded: list[dict[str, Any]] = []
            sequence = 0
            final_text: str | None = None

            try:
                while True:
                    budget.begin_iteration()

                    response = await self.model.complete(
                        system=system,
                        messages=messages,
                        tools=[tool.to_schema() for tool in tools],
                        timeout_s=budget.remaining_seconds(),
                    )
                    budget.spend_tokens(response.total_tokens)

                    # Checkpoint after each model turn so a restart resumes
                    # rather than replaying from the beginning.
                    await checkpoint.save_state(run.id, messages, budget.iterations)

                    if not response.tool_calls:
                        final_text = response.text
                        break

                    messages.append(
                        {
                            "role": "assistant",
                            "content": response.text or "",
                            "tool_calls": [
                                {"id": c.id, "name": c.name, "arguments": c.arguments}
                                for c in response.tool_calls
                            ],
                        }
                    )

                    for request in response.tool_calls:
                        sequence += 1
                        outcome = await self._invoke_tool(
                            session,
                            run=run,
                            sequence=sequence,
                            request=request,
                            tool_map=tool_map,
                            user_id=user_id,
                            trigger=trigger,
                            trust=capability.trust,
                            skill_version_id=skill_version_id,
                        )
                        recorded.append(outcome)
                        messages.append(
                            {
                                "role": "tool",
                                "content": prompt.render_tool_result(
                                    request.name,
                                    outcome["error"]
                                    if outcome["error"] is not None
                                    else outcome["result"],
                                ),
                                "tool_call_id": request.id,
                            }
                        )

            except LimitExceeded as exc:
                log.warning("agent.run.limit", kind=exc.kind, **budget.snapshot())
                return await self._finish(
                    session,
                    run,
                    enums.RunStatus.limit_exceeded,
                    output=None,
                    budget=budget,
                    error=f"{exc.kind}: {exc.detail}",
                    tool_calls=recorded,
                )
            except Exception as exc:  # noqa: BLE001
                log.exception("agent.run.failed", error_type=type(exc).__name__)
                return await self._finish(
                    session,
                    run,
                    enums.RunStatus.failed,
                    output=None,
                    budget=budget,
                    error=f"{type(exc).__name__}: {exc}",
                    tool_calls=recorded,
                )

            return await self._finish(
                session,
                run,
                enums.RunStatus.succeeded,
                output=final_text,
                budget=budget,
                tool_calls=recorded,
            )

    async def _invoke_tool(
        self,
        session: AsyncSession,
        *,
        run: Run,
        sequence: int,
        request: ToolRequest,
        tool_map: dict[str, ToolSpec],
        user_id: uuid.UUID,
        trigger: enums.TriggerType,
        trust: enums.TrustLevel,
        skill_version_id: uuid.UUID | None,
    ) -> dict[str, Any]:
        """Run one tool call, audit it, and never let it raise into the loop.

        A tool failure is information for the model — it can try something else —
        so failures come back as a result, not an exception. Everything is
        recorded either way.
        """
        started = time.perf_counter()
        started_at = datetime.now(UTC)
        result: dict[str, Any] | None = None
        error: str | None = None

        tool = tool_map.get(request.name)

        if tool is None:
            # The model named a tool it was not given. This is the case worth
            # logging loudly: it is what an injection attempt looks like.
            error = (
                f"No tool named {request.name!r} is available in this run. "
                f"Available: {sorted(tool_map)}."
            )
            log.warning(
                "agent.tool.not_bound",
                requested=request.name,
                trigger=trigger.value,
                trust=trust.value,
            )
        else:
            try:
                await self.breaker.check(tool.name)
                args = tool.args_model.model_validate(request.arguments)
                context = ToolContext(
                    run_id=run.id,
                    user_id=user_id,
                    trigger=trigger,
                    trust=trust,
                    session=session,
                )
                # A savepoint, so a tool that fails against the database does
                # not take the audit record down with it. Without this, a failed
                # statement leaves the transaction aborted, the ToolCall insert
                # below fails too, and the one thing we promise to always record
                # is the thing that disappears. Rolling back to the savepoint
                # also makes a tool call atomic: a handler that half-wrote
                # before raising leaves nothing behind.
                async with session.begin_nested():
                    result = await tool.handler(context, args)
                await self.breaker.record_success(tool.name)
            except CircuitOpenError as exc:
                error = str(exc)
            except ValidationError as exc:
                error = f"Invalid arguments for {tool.name}: {exc.errors()}"
            except Exception as exc:  # noqa: BLE001
                error = f"{type(exc).__name__}: {exc}"
                await self.breaker.record_failure(tool.name)

        duration_ms = int((time.perf_counter() - started) * 1000)

        session.add(
            ToolCall(
                run_id=run.id,
                sequence=sequence,
                tool_name=request.name,
                arguments=request.arguments,
                result=result,
                error=error,
                duration_ms=duration_ms,
                skill_version_id=skill_version_id,
                started_at=started_at,
            )
        )
        await session.flush()

        log.info(
            "agent.tool.call",
            tool=request.name,
            sequence=sequence,
            duration_ms=duration_ms,
            ok=error is None,
        )
        return {
            "sequence": sequence,
            "tool": request.name,
            "arguments": request.arguments,
            "result": result,
            "error": error,
            "duration_ms": duration_ms,
        }

    async def _finish(
        self,
        session: AsyncSession,
        run: Run,
        status: enums.RunStatus,
        *,
        output: str | None,
        budget: RunBudget | None,
        error: str | None = None,
        tool_calls: list[dict[str, Any]] | None = None,
    ) -> RunResult:
        ended = datetime.now(UTC)
        run.status = status
        run.ended_at = ended
        run.duration_ms = int((ended - run.started_at).total_seconds() * 1000)
        run.token_cost = budget.tokens if budget else 0
        run.iterations = budget.iterations if budget else 0
        run.error = error
        run.summary = output
        await session.flush()

        log.info(
            "agent.run.end",
            status=status.value,
            iterations=run.iterations,
            token_cost=run.token_cost,
            duration_ms=run.duration_ms,
        )
        return RunResult(
            run_id=run.id,
            status=status,
            output=output,
            bound_tools=list(run.bound_tools),
            iterations=run.iterations,
            token_cost=run.token_cost,
            tool_calls=tool_calls or [],
            error=error,
        )
