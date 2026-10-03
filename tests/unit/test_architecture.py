"""Layering: the domain is pure; only integrations know ORBIT/FORGE payloads."""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2] / "nova"
FORBIDDEN_IN_DOMAIN = (
    "fastapi",
    "sqlalchemy",
    "httpx",
    "langgraph",
    "redis",
    "celery",
    "nova.infra",
    "nova.integrations",
    "nova.agent",
)


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text())
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names |= {a.name for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    return names


def test_domain_is_pure():
    for path in (ROOT / "domain").glob("*.py"):
        bad = [m for m in _imports(path) if m.startswith(FORBIDDEN_IN_DOMAIN)]
        assert not bad, f"{path.name} imports {bad}"


def test_agent_does_not_depend_on_orbit_or_forge_or_the_database():
    for path in (ROOT / "agent").rglob("*.py"):
        bad = [
            m for m in _imports(path) if m.startswith(("nova.integrations", "nova.infra.models", "sqlalchemy", "nova.services"))
        ]
        assert not bad, f"{path.relative_to(ROOT)} imports {bad}"


def test_orbit_and_forge_payloads_stay_in_integrations():
    for path in ROOT.rglob("*.py"):
        if "integrations" in path.parts:
            continue
        bad = [m for m in _imports(path) if m.startswith(("nova.integrations.orbit.schemas", "nova.integrations.forge.schemas"))]
        assert not bad, f"{path.relative_to(ROOT)} imports {bad}"
