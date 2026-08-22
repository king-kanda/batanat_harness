"""Structured JSON logging.

One log format everywhere: a single JSON object per line, on stdout, carrying
`run_id` whenever a run context is active. Standard-library loggers (uvicorn,
asyncpg, httpx) are routed through the same pipeline so nothing escapes as
unstructured text.

Secrets are redacted at the processor level rather than at each call site. The
rule the whole project relies on — OAuth tokens are never logged — must not
depend on every future author remembering it.
"""

from __future__ import annotations

import logging
import sys
from typing import Any

import structlog

REDACTED = "«redacted»"

# Any event-dict key containing one of these substrings has its value replaced.
SENSITIVE_KEY_PARTS = (
    "token",
    "password",
    "secret",
    "authorization",
    "api_key",
    "apikey",
    "client_secret",
    "refresh",
    "credential",
    "cookie",
)


def _redact(_logger: Any, _method: str, event_dict: dict[str, Any]) -> dict[str, Any]:
    """Replace values of sensitive-looking keys, recursively."""

    def scrub(value: Any) -> Any:
        if isinstance(value, dict):
            return {k: (REDACTED if _is_sensitive(k) else scrub(v)) for k, v in value.items()}
        if isinstance(value, (list, tuple)):
            return [scrub(v) for v in value]
        return value

    return {k: (REDACTED if _is_sensitive(k) else scrub(v)) for k, v in event_dict.items()}


class _StdoutProxy:
    """Resolve `sys.stdout` at write time, not at handler construction.

    `logging.StreamHandler(sys.stdout)` captures the stream object once. Anything
    that later replaces stdout — a test harness, an embedded runner — then loses
    the log output to a dead stream. Looking it up per write costs nothing here.
    """

    def write(self, message: str) -> int:
        return sys.stdout.write(message)

    def flush(self) -> None:
        sys.stdout.flush()


def _is_sensitive(key: Any) -> bool:
    if not isinstance(key, str):
        return False
    lowered = key.lower()
    return any(part in lowered for part in SENSITIVE_KEY_PARTS)


def configure_logging(level: str = "info") -> None:
    """Idempotently configure structlog + stdlib logging for JSON output."""
    numeric_level = getattr(logging, level.upper(), logging.INFO)

    shared_processors: list[Any] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        _redact,
    ]

    structlog.configure(
        processors=[
            *shared_processors,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    formatter = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=shared_processors,
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            structlog.processors.JSONRenderer(),
        ],
    )

    handler = logging.StreamHandler(_StdoutProxy())
    handler.setFormatter(formatter)

    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(numeric_level)

    # uvicorn installs its own handlers; strip them so output stays single-format.
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        stdlib_logger = logging.getLogger(name)
        stdlib_logger.handlers = []
        stdlib_logger.propagate = True


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    return structlog.get_logger(name)
