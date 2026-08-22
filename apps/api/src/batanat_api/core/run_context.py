"""Correlation context.

Every unit of work — an HTTP request, a scheduled run, a webhook delivery — gets
a `run_id`. It is stored in a contextvar so any code, at any depth, can log
against it without threading a parameter through every call.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar

import structlog

_run_id: ContextVar[str | None] = ContextVar("run_id", default=None)


def new_run_id() -> str:
    return uuid.uuid4().hex


def get_run_id() -> str | None:
    return _run_id.get()


def set_run_id(run_id: str) -> None:
    """Bind a run id to the current context and to structlog's contextvars."""
    _run_id.set(run_id)
    structlog.contextvars.bind_contextvars(run_id=run_id)


@contextmanager
def run_context(run_id: str | None = None) -> Iterator[str]:
    """Scope a block of work to a run id, restoring the previous one on exit."""
    rid = run_id or new_run_id()
    token = _run_id.set(rid)
    structlog.contextvars.bind_contextvars(run_id=rid)
    try:
        yield rid
    finally:
        _run_id.reset(token)
        structlog.contextvars.unbind_contextvars("run_id")
