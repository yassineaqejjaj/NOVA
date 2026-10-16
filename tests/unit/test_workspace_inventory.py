"""Inventory of workspace filters (ADR 001 §9, NOV-107): a table or a route nobody declared fails this test.

The filter itself is applied centrally (``nova/infra/scope.py``): every table of the model is workspace-scoped unless it is
listed in ``TABLE_EXCEPTIONS`` below, and every API route runs after authentication, which scopes the request, unless it is
listed in ``ROUTE_EXCEPTIONS``. Adding a table or a route without choosing fails here; the lists are the review surface.
"""

from __future__ import annotations

import re
from pathlib import Path

import httpx

from nova.infra import models  # noqa: F401 - registers the tables
from nova.infra.db import Base
from nova.infra.scope import WorkspaceScoped
from nova_api.auth import current_principal
from nova_api.errors import ApiError
from nova_api.main import create_app

ROOT = Path(__file__).resolve().parents[2]

#: Tables without ``workspace_id``, and why. Everything else holds tenant data and carries it (NOT NULL).
TABLE_EXCEPTIONS = {
    "workspaces": "the registry of workspaces itself",
    "skills": "the Skill catalog: the same library for every workspace (synced from files at start-up)",
    "skill_versions": "versions of the Skill catalog",
    "agent_policies": "lessons the agents learned from FORGE: one learning loop for the platform (docs/TRAINING.md)",
    "releases": "canary releases of those policies: platform level",
    "training_cycles": "FORGE training cycles of the agents: platform level",
    "email_codes": "one-time codes of sign-up and password reset: they exist before any account (so any workspace)",
    "dev_identities": "password accounts of development and tests (NOVA_AUTH_MODE=dev): sign-in bootstrap",
}

#: Routes that do not run after ``current_principal`` (so are not scoped by it), and what protects them instead.
ROUTE_EXCEPTIONS = {
    ("GET", "/api/v1/auth/config"): "public sign-in screen configuration",
    ("GET", "/api/v1/auth/login"): "redirect to the identity provider",
    (
        "GET",
        "/api/v1/auth/callback",
    ): "OIDC callback: the workspace comes from the validated id token (create) and is checked against the account",
    ("POST", "/api/v1/auth/dev-login"): "development sign-in, refused in production; accounts live in the default workspace",
    ("POST", "/api/v1/auth/password-login"): "sign-in: the session it opens is scoped by the account's workspace afterwards",
    ("POST", "/api/v1/auth/signup"): "sign-up: new accounts live in the default workspace until an IdP says otherwise",
    ("POST", "/api/v1/auth/signup/resend"): "sign-up",
    ("POST", "/api/v1/auth/signup/verify"): "sign-up",
    ("POST", "/api/v1/auth/password/forgot"): "password reset by e-mailed code",
    ("POST", "/api/v1/auth/password/reset"): "password reset by e-mailed code",
    ("GET", "/api/v1/auth/dev/outbox"): "development mail outbox, refused in production",
    ("POST", "/api/v1/auth/logout"): "drops the session cookie",
    ("POST", "/api/v1/webhooks/orbit"): "HMAC-signed ORBIT event: the workspace is resolved from the signed payload or the "
    "projects that reference the ORBIT project (revocation.event_workspaces), then everything runs under that scope",
    ("POST", "/v1/agents/{nova_agent_id}/runs"): "NOVA Agent Protocol for FORGE: inbound bearer token, runs as the service "
    "user of the default workspace until FORGE carries a workspace",
}


#: Routes outside the OpenAPI schema (probes): public, no data.
INFRA_ROUTES = {("GET", "/health"), ("GET", "/ready")}


async def _operations() -> dict[tuple[str, str], bool]:
    """(method, path) of every operation of the API -> does it run after ``current_principal``?

    Asked of the application itself rather than of FastAPI's routing internals: ``current_principal`` is replaced by a
    stand-in that answers 418, then every operation of the OpenAPI schema is called without credentials: the ones that
    answer 418 are behind authentication (hence scoped to the workspace of the request), the others are not.
    """
    app = create_app()

    async def stand_in() -> None:
        raise ApiError(418, "scoped", "the request is scoped by current_principal")

    app.dependency_overrides[current_principal] = stand_in
    found: dict[tuple[str, str], bool] = {}
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app, raise_app_exceptions=False), base_url="http://test"
    ) as client:
        for path, operations in app.openapi()["paths"].items():
            for method in (m for m in operations if m in ("get", "post", "put", "patch", "delete")):
                response = await client.request(method.upper(), re.sub(r"\{[^}]+\}", "x", path))
                found[(method.upper(), path)] = response.status_code == 418
    return found


def test_every_table_is_workspace_scoped_or_declared_an_exception():
    scoped = {m.local_table.name for m in Base.registry.mappers if issubclass(m.class_, WorkspaceScoped)}
    tables = set(Base.metadata.tables)
    undeclared = sorted(tables - scoped - set(TABLE_EXCEPTIONS))
    assert not undeclared, (
        f"Tables without a workspace filter nor a declared exception: {undeclared}. Give the model the WorkspaceScoped mixin "
        "(and add the column to a migration), or list the table in TABLE_EXCEPTIONS with the reason."
    )
    stale = sorted(set(TABLE_EXCEPTIONS) - tables)
    assert not stale, f"TABLE_EXCEPTIONS lists tables that do not exist: {stale}"
    carrying = sorted(t for t in TABLE_EXCEPTIONS if "workspace_id" in Base.metadata.tables[t].c)
    assert not carrying, f"{carrying} carry workspace_id: they are not exceptions"
    for table in scoped:
        column = Base.metadata.tables[table].c.workspace_id
        assert column.nullable is False, f"{table}.workspace_id must be NOT NULL"


async def test_every_route_is_scoped_by_authentication_or_declared_an_exception():
    operations = await _operations()
    assert len(operations) > 120  # the whole API was inspected, not an empty schema
    undeclared = sorted(k for k, scoped in operations.items() if not scoped and k not in ROUTE_EXCEPTIONS)
    assert not undeclared, (
        f"Routes that are neither authenticated (so scoped to the workspace of the request) nor declared: {undeclared}. "
        "Use the CurrentPrincipal dependency, or list the route in ROUTE_EXCEPTIONS with what protects it."
    )
    known = set(operations) | INFRA_ROUTES
    stale = sorted(set(ROUTE_EXCEPTIONS) - known)
    assert not stale, f"ROUTE_EXCEPTIONS lists routes that do not exist: {stale}"
    wrongly = sorted(k for k in ROUTE_EXCEPTIONS if operations.get(k))
    assert not wrongly, f"{wrongly} are authenticated: they are not exceptions"


def test_no_route_takes_its_workspace_from_the_caller():
    """The workspace of a request comes from the validated token, never from a parameter, a header or a body (§9, rule 2)."""
    offenders: list[str] = []

    def walk(node, where: str) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                if isinstance(key, str) and "workspace" in key.lower():
                    offenders.append(f"{where}: {key}")
                if key == "name" and isinstance(value, str) and "workspace" in value.lower():
                    offenders.append(f"{where}: parameter {value}")
                walk(value, f"{where}/{key}")
        elif isinstance(node, list):
            for item in node:
                walk(item, where)

    walk(create_app().openapi(), "openapi")
    assert not offenders, f"A route reads a workspace from the request: {offenders}"


#: Statements that bypass the ORM, hence the workspace filter, with the reason each is acceptable.
BYPASS_ALLOWED = {
    ("apps/api/nova_api/main.py", "raw SQL (text)"): "SELECT 1 of the readiness probe",
    ("nova/services/accounts.py", "raw SQL (text)"): "pg_advisory_xact_lock of the demo account: reads no table",
    ("nova/services/skills_sync.py", "raw SQL (text)"): "pg_advisory_xact_lock of the Skill catalog sync: reads no table",
}
BYPASS_PATTERNS = {
    "raw SQL (text)": r"^from sqlalchemy(?:\.\w+)* import [^\n]*\btext\b|\bsa\.text\(",
    "Core table statement": r"\.__table__\.(?:update|insert|delete)\(",
    "driver SQL": r"\bexec_driver_sql\(",
}


def test_no_code_bypasses_the_orm_filter_without_review():
    """Core statements and raw SQL are not filtered by workspace: none may appear unless it is listed above."""
    found = set()
    for base in ("nova", "apps/api", "services"):
        for path in (ROOT / base).rglob("*.py"):
            source = path.read_text()
            for name, pattern in BYPASS_PATTERNS.items():
                if re.search(pattern, source, re.M):
                    found.add((str(path.relative_to(ROOT)), name))
    unreviewed = sorted(found - set(BYPASS_ALLOWED))
    assert not unreviewed, f"Code that bypasses the workspace filter; review it, then list it in BYPASS_ALLOWED: {unreviewed}"
    assert not sorted(set(BYPASS_ALLOWED) - found), "BYPASS_ALLOWED lists code that no longer exists"
