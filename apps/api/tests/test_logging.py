"""Logging pipeline: JSON output, run-id correlation, secret redaction."""

from __future__ import annotations

import json
import logging

import pytest
import structlog

from batanat_api.core.logging import REDACTED, configure_logging, get_logger
from batanat_api.core.run_context import get_run_id, run_context


@pytest.fixture(autouse=True)
def _reset_logging() -> None:
    configure_logging("debug")


def _emit(capsys: pytest.CaptureFixture[str], **kwargs: object) -> dict:
    get_logger("test").info("test.event", **kwargs)
    line = capsys.readouterr().out.strip().splitlines()[-1]
    return json.loads(line)


def test_log_lines_are_json_with_level_and_timestamp(capsys: pytest.CaptureFixture[str]) -> None:
    record = _emit(capsys, thing="value")
    assert record["event"] == "test.event"
    assert record["level"] == "info"
    assert record["thing"] == "value"
    assert "timestamp" in record


def test_run_id_is_threaded_through_the_context(capsys: pytest.CaptureFixture[str]) -> None:
    with run_context("run-42") as rid:
        assert rid == "run-42"
        assert get_run_id() == "run-42"
        record = _emit(capsys)
    assert record["run_id"] == "run-42"

    # ...and is gone once the context closes.
    after = _emit(capsys)
    assert "run_id" not in after
    assert get_run_id() is None


@pytest.mark.parametrize(
    "key",
    ["access_token", "refresh_token", "client_secret", "password", "Authorization", "api_key"],
)
def test_sensitive_keys_are_redacted(capsys: pytest.CaptureFixture[str], key: str) -> None:
    record = _emit(capsys, **{key: "super-secret-value"})
    assert record[key] == REDACTED
    assert "super-secret-value" not in json.dumps(record)


def test_redaction_reaches_nested_structures(capsys: pytest.CaptureFixture[str]) -> None:
    record = _emit(
        capsys,
        connection={"provider": "zoho", "tokens": {"refresh_token": "leak-me"}},
        items=[{"password": "leak-me-too"}],
    )
    blob = json.dumps(record)
    assert "leak-me" not in blob
    assert record["connection"]["provider"] == "zoho"


def test_stdlib_loggers_are_routed_through_the_same_pipeline(
    capsys: pytest.CaptureFixture[str],
) -> None:
    logging.getLogger("uvicorn.error").warning("plain stdlib message")
    line = capsys.readouterr().out.strip().splitlines()[-1]
    record = json.loads(line)
    assert record["event"] == "plain stdlib message"
    assert record["level"] == "warning"


def test_configure_logging_is_idempotent(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging("info")
    configure_logging("info")
    get_logger("test").info("once")
    assert len(capsys.readouterr().out.strip().splitlines()) == 1
    assert len(logging.getLogger().handlers) == 1
    structlog.contextvars.clear_contextvars()
