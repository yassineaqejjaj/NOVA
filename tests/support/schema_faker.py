"""Generate a deterministic instance of a JSON Schema (test fixtures and the fake inference server)."""

from __future__ import annotations

from typing import Any


def fake(schema: dict[str, Any], *, path: str = "", citations: list[str] | None = None, n_items: int = 2) -> Any:
    if "anyOf" in schema:
        return fake(next(s for s in schema["anyOf"] if s.get("type") != "null"), path=path, citations=citations, n_items=n_items)
    if "enum" in schema:
        return schema["enum"][0]
    kind = schema.get("type")
    if isinstance(kind, list):
        kind = next((k for k in kind if k != "null"), "string")
    name = path.rsplit(".", 1)[-1]
    if kind == "object":
        props = schema.get("properties", {})
        result = {}
        for key, sub in props.items():
            if key == "tool_requests":
                result[key] = []
                continue
            result[key] = fake(sub, path=f"{path}.{key}", citations=citations, n_items=n_items)
        if "id" in result and isinstance(result["id"], str):
            result["id"] = f"{path.split('.')[-2] if '.' in path else 'item'}-{abs(hash(path)) % 97}"
        return result
    if kind == "array":
        if name == "citations":
            return list(citations or [])
        count = max(schema.get("minItems", 0), n_items)
        if schema.get("maxItems") is not None:
            count = min(count, schema["maxItems"])
        return [fake(schema.get("items", {}), path=f"{path}[{i}]", citations=citations, n_items=n_items) for i in range(count)]
    if kind == "integer":
        return 1
    if kind == "number":
        return 1.0
    if kind == "boolean":
        return False
    if name == "parent_id":
        return None
    return f"Generated {name or 'text'}"
