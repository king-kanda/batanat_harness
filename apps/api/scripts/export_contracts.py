"""Generate the shared contracts consumed by the web app.

Pydantic models in `batanat_api.contracts` are the single source of truth. This
script emits two artefacts into `packages/schema/src/generated/`:

    contracts.json  — the JSON Schema bundle (all models under $defs)
    contracts.ts    — TypeScript types

The TS emitter is deliberately small and handles only the JSON Schema shapes
Pydantic produces for our models: objects, enums, arrays, unions with null,
records, and literals. If a future contract needs something it cannot express,
it raises rather than guessing — a loud failure beats a wrong type.

Usage:  uv run python scripts/export_contracts.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from pydantic.json_schema import models_json_schema  # noqa: E402

from batanat_api.contracts import EXPORTED_MODELS  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[3]
OUT_DIR = REPO_ROOT / "packages" / "schema" / "src" / "generated"

HEADER = """// AUTO-GENERATED — do not edit.
// Source: apps/api/src/batanat_api/contracts/*.py
// Regenerate: make types
"""

SCALARS = {
    "string": "string",
    "integer": "number",
    "number": "number",
    "boolean": "boolean",
    "null": "null",
}


def build_schema() -> dict[str, Any]:
    _, bundle = models_json_schema(
        [(model, "serialization") for model in EXPORTED_MODELS],
        ref_template="#/$defs/{model}",
        title="BatanatContracts",
    )
    return bundle


def ts_type(node: dict[str, Any]) -> str:
    """Map one JSON Schema node to a TypeScript type expression."""
    if "$ref" in node:
        return node["$ref"].rsplit("/", 1)[-1]

    if "const" in node:
        return json.dumps(node["const"])

    for union_key in ("anyOf", "oneOf"):
        if union_key in node:
            parts = [ts_type(sub) for sub in node[union_key]]
            deduped = list(dict.fromkeys(parts))
            return " | ".join(deduped)

    if "enum" in node:
        return " | ".join(json.dumps(v) for v in node["enum"])

    node_type = node.get("type")

    if node_type == "array":
        items = node.get("items")
        return f"{ts_type(items)}[]" if items else "unknown[]"

    if node_type == "object":
        extra = node.get("additionalProperties")
        if isinstance(extra, dict):
            return f"Record<string, {ts_type(extra)}>"
        return "Record<string, unknown>"

    if isinstance(node_type, list):
        return " | ".join(SCALARS.get(t, "unknown") for t in node_type)

    if node_type in SCALARS:
        return SCALARS[node_type]

    if not node:  # empty schema == Any
        return "unknown"

    raise ValueError(f"Cannot express JSON Schema node as TypeScript: {node!r}")


def render_definition(name: str, definition: dict[str, Any]) -> str:
    doc = definition.get("description")
    lines: list[str] = []
    if doc:
        lines.append("/** " + " ".join(doc.split()) + " */")

    if "enum" in definition and "properties" not in definition:
        members = " | ".join(json.dumps(v) for v in definition["enum"])
        lines.append(f"export type {name} = {members};")
        return "\n".join(lines)

    properties: dict[str, Any] = definition.get("properties", {})
    required: set[str] = set(definition.get("required", []))

    lines.append(f"export interface {name} {{")
    for prop_name, prop_schema in properties.items():
        prop_doc = prop_schema.get("description")
        if prop_doc:
            lines.append("  /** " + " ".join(prop_doc.split()) + " */")
        optional = "" if prop_name in required else "?"
        lines.append(f"  {prop_name}{optional}: {ts_type(prop_schema)};")
    lines.append("}")
    return "\n".join(lines)


def render_typescript(bundle: dict[str, Any]) -> str:
    defs: dict[str, Any] = bundle.get("$defs", {})
    blocks = [render_definition(name, defs[name]) for name in sorted(defs)]
    return HEADER + "\n" + "\n\n".join(blocks) + "\n"


def main() -> None:
    bundle = build_schema()
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    json_path = OUT_DIR / "contracts.json"
    ts_path = OUT_DIR / "contracts.ts"

    json_path.write_text(json.dumps(bundle, indent=2) + "\n", encoding="utf-8")
    ts_path.write_text(render_typescript(bundle), encoding="utf-8")

    print(f"wrote {json_path.relative_to(REPO_ROOT)}")
    print(f"wrote {ts_path.relative_to(REPO_ROOT)}")


if __name__ == "__main__":
    main()
