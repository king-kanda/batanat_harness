"""The Pydantic → TypeScript contract generator."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "export_contracts.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("export_contracts", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["export_contracts"] = module
    spec.loader.exec_module(module)
    return module


export_contracts = _load_module()


def test_bundle_contains_every_exported_model() -> None:
    defs = export_contracts.build_schema()["$defs"]
    assert {"HealthResponse", "ServiceHealth", "ErrorResponse", "ServiceStatus"} <= set(defs)


def test_typescript_renders_interfaces_enums_and_optionals() -> None:
    ts = export_contracts.render_typescript(export_contracts.build_schema())

    assert "export interface HealthResponse {" in ts
    assert 'export type ServiceStatus = "ok" | "degraded" | "down";' in ts
    assert "services: ServiceHealth[];" in ts
    # nullable-with-default fields are optional and unioned with null
    assert "latency_ms?: number | null;" in ts
    # required fields carry no `?`
    assert "status: ServiceStatus;" in ts


@pytest.mark.parametrize(
    ("node", "expected"),
    [
        ({"type": "string"}, "string"),
        ({"type": "integer"}, "number"),
        ({"type": "boolean"}, "boolean"),
        ({"type": "array", "items": {"type": "string"}}, "string[]"),
        ({"anyOf": [{"type": "string"}, {"type": "null"}]}, "string | null"),
        ({"$ref": "#/$defs/ServiceHealth"}, "ServiceHealth"),
        ({"type": "object", "additionalProperties": {"type": "number"}}, "Record<string, number>"),
        ({}, "unknown"),
    ],
)
def test_ts_type_mapping(node: dict, expected: str) -> None:
    assert export_contracts.ts_type(node) == expected


def test_unmappable_node_raises_rather_than_guessing() -> None:
    with pytest.raises(ValueError):
        export_contracts.ts_type({"type": "some-future-thing"})
