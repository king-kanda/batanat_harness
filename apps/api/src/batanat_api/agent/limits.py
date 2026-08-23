"""Loop limits and the per-tool circuit breaker.

An agent that loops is not a hypothetical: a tool that keeps failing, a model
that keeps retrying it, and a schedule that fires twice a day is enough to spend
a lot of money overnight. Three independent limits, because each catches a
different failure:

* **iterations** — the model calling tools forever without concluding.
* **token budget** — a small number of iterations over enormous payloads.
* **wall clock** — a tool that hangs rather than fails.

All three are configurable, all three are enforced in the loop, and all three
end the run as `limit_exceeded` rather than `failed`, so the Activity screen can
distinguish "this broke" from "this was stopped".

The circuit breaker is separate and per-tool: after N consecutive failures a
tool is refused for a cooldown, so a dead scraper degrades one source instead of
burning every run's iteration budget.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import UTC, datetime

from batanat_api.config import get_settings
from batanat_api.core.logging import get_logger
from batanat_api.core.redis import get_redis

log = get_logger(__name__)


class LimitExceeded(RuntimeError):
    """A run hit one of its budgets. Carries which one, for the audit trail."""

    def __init__(self, kind: str, detail: str):
        super().__init__(detail)
        self.kind = kind
        self.detail = detail


@dataclass
class RunLimits:
    max_iterations: int
    token_budget: int
    wall_clock_seconds: float

    @classmethod
    def from_settings(cls) -> RunLimits:
        settings = get_settings()
        return cls(
            max_iterations=settings.agent_max_iterations,
            token_budget=settings.agent_token_budget,
            wall_clock_seconds=settings.agent_wall_clock_timeout_s,
        )


@dataclass
class RunBudget:
    """Mutable accounting for one run. Checked before every model call."""

    limits: RunLimits
    iterations: int = 0
    tokens: int = 0
    started_monotonic: float = field(default_factory=time.monotonic)
    started_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    @property
    def elapsed_seconds(self) -> float:
        return time.monotonic() - self.started_monotonic

    def spend_tokens(self, count: int) -> None:
        self.tokens += max(0, count)

    def begin_iteration(self) -> None:
        """Raise if this run may not take another step."""
        if self.iterations >= self.limits.max_iterations:
            raise LimitExceeded(
                "max_iterations",
                f"Stopped after {self.iterations} iterations (limit {self.limits.max_iterations}).",
            )
        if self.tokens >= self.limits.token_budget:
            raise LimitExceeded(
                "token_budget",
                f"Stopped after {self.tokens} tokens (budget {self.limits.token_budget}).",
            )
        if self.elapsed_seconds >= self.limits.wall_clock_seconds:
            raise LimitExceeded(
                "wall_clock",
                f"Stopped after {self.elapsed_seconds:.1f}s "
                f"(limit {self.limits.wall_clock_seconds}s).",
            )
        self.iterations += 1

    def remaining_seconds(self) -> float:
        return max(0.0, self.limits.wall_clock_seconds - self.elapsed_seconds)

    def snapshot(self) -> dict[str, float | int]:
        return {
            "iterations": self.iterations,
            "tokens": self.tokens,
            "elapsed_seconds": round(self.elapsed_seconds, 2),
        }


# --- circuit breaker ---------------------------------------------------------


class CircuitOpenError(RuntimeError):
    """The tool is disabled after repeated failures."""


class CircuitBreaker:
    """Per-tool failure counter in Redis, shared across processes.

    Redis rather than memory because the scheduler and the API are separate
    processes: a scraper that has failed five times from the cron should also be
    refused when a chat turn reaches for it.
    """

    def __init__(self, *, threshold: int | None = None, cooldown_seconds: int | None = None):
        settings = get_settings()
        self.threshold = threshold or settings.tool_circuit_breaker_threshold
        self.cooldown_seconds = cooldown_seconds or settings.tool_circuit_breaker_cooldown_s

    @staticmethod
    def _failure_key(tool: str) -> str:
        return f"breaker:failures:{tool}"

    @staticmethod
    def _open_key(tool: str) -> str:
        return f"breaker:open:{tool}"

    async def is_open(self, tool: str) -> bool:
        client = get_redis()
        try:
            return await client.exists(self._open_key(tool)) == 1
        except Exception:  # noqa: BLE001 — Redis down must not disable every tool
            log.warning("breaker.unavailable", tool=tool)
            return False

    async def check(self, tool: str) -> None:
        if await self.is_open(tool):
            raise CircuitOpenError(
                f"{tool} is temporarily disabled after {self.threshold} consecutive "
                f"failures. It will be retried automatically in up to "
                f"{self.cooldown_seconds // 60} minutes."
            )

    async def record_success(self, tool: str) -> None:
        """One success clears the count — we care about *consecutive* failures."""
        try:
            await get_redis().delete(self._failure_key(tool))
        except Exception:  # noqa: BLE001
            pass

    async def record_failure(self, tool: str) -> bool:
        """Count a failure; open the circuit at the threshold. Returns True if opened."""
        client = get_redis()
        try:
            failures = await client.incr(self._failure_key(tool))
            # Keep the counter alive only as long as the cooldown window.
            await client.expire(self._failure_key(tool), self.cooldown_seconds)

            if failures >= self.threshold:
                await client.set(self._open_key(tool), "1", ex=self.cooldown_seconds)
                log.warning(
                    "breaker.opened",
                    tool=tool,
                    failures=failures,
                    cooldown_seconds=self.cooldown_seconds,
                )
                return True
            return False
        except Exception:  # noqa: BLE001
            return False

    async def reset(self, tool: str) -> None:
        await get_redis().delete(self._failure_key(tool), self._open_key(tool))
