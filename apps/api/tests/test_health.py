"""Health endpoint and probe-aggregation behaviour.

These tests do not require Docker: the probes are replaced with fakes. The
point is the contract and the aggregation rule, not the drivers.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from batanat_api.config import Settings
from batanat_api.contracts.health import ServiceHealth, ServiceStatus
from batanat_api.health import checks
from batanat_api.main import create_app


def _service(name: str, status: ServiceStatus) -> ServiceHealth:
    return ServiceHealth(name=name, status=status, latency_ms=1.0, checked_at=datetime.now(UTC))


@pytest.fixture
def client() -> TestClient:
    return TestClient(create_app())


def test_live_endpoint_touches_nothing_external(client: TestClient) -> None:
    response = client.get("/api/health/live")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_health_reports_every_dependency(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    names = ("postgres", "qdrant", "mongo", "redis")

    async def fake_check_all(_settings: Settings) -> list[ServiceHealth]:
        return [_service(name, ServiceStatus.ok) for name in names]

    monkeypatch.setattr("batanat_api.health.router.check_all", fake_check_all)

    response = client.get("/api/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert [s["name"] for s in body["services"]] == ["postgres", "qdrant", "mongo", "redis"]


def test_readiness_returns_503_when_a_dependency_is_down(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def fake_check_all(_settings: Settings) -> list[ServiceHealth]:
        return [_service("postgres", ServiceStatus.down), _service("redis", ServiceStatus.ok)]

    monkeypatch.setattr("batanat_api.health.router.check_all", fake_check_all)

    response = client.get("/api/health/ready")
    assert response.status_code == 503
    assert response.json()["status"] == "down"


def test_response_carries_the_run_id_header(client: TestClient) -> None:
    response = client.get("/api/health/live", headers={"x-run-id": "abc123"})
    assert response.headers["x-run-id"] == "abc123"


@pytest.mark.parametrize(
    ("statuses", "expected"),
    [
        ([ServiceStatus.ok, ServiceStatus.ok], ServiceStatus.ok),
        ([ServiceStatus.ok, ServiceStatus.degraded], ServiceStatus.degraded),
        ([ServiceStatus.degraded, ServiceStatus.down], ServiceStatus.down),
        ([], ServiceStatus.ok),
    ],
)
def test_overall_status_takes_the_worst(
    statuses: list[ServiceStatus], expected: ServiceStatus
) -> None:
    services = [_service(f"svc{i}", s) for i, s in enumerate(statuses)]
    assert checks.overall_status(services) is expected


async def test_probe_converts_failure_into_down_instead_of_raising() -> None:
    async def boom() -> str:
        raise ConnectionRefusedError("nothing listening")

    result = await checks._probe("postgres", boom, timeout_s=1.0)
    assert result.status is ServiceStatus.down
    assert "ConnectionRefusedError" in (result.detail or "")


async def test_probe_times_out_rather_than_hanging() -> None:
    import asyncio

    async def slow() -> str:
        await asyncio.sleep(5)
        return "never"

    result = await checks._probe("mongo", slow, timeout_s=0.05)
    assert result.status is ServiceStatus.down
    assert "timed out" in (result.detail or "")
