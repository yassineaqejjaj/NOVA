"""Migration 0020 (workspaces) on a POPULATED database, SQLite and PostgreSQL (NOV-107).

The database is built at the schema of an older revision (0015, then 0019 = what production runs from ``main``), filled with
synthetic rows in every table, migrated up, down and up again. Nothing may be lost or changed outside the new columns:
row counts and a hash of every pre-existing column are compared at each step.

PostgreSQL runs when ``NOVA_DATABASE_URL`` points to one (the CI job does): the test creates, and drops, its own database.
"""

from __future__ import annotations

import hashlib
import os
import subprocess
import sys
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
import sqlalchemy as sa
from sqlalchemy.engine import Engine

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_WORKSPACE = uuid.UUID("00000000-0000-4000-8000-000000000001")
PROJECT_NAMESPACE = uuid.UUID("6f5c1a52-9f0e-4c1b-8d9a-0a1b2c3d4e5f")
NOW = datetime(2026, 10, 1, 8, 30, tzinfo=UTC)
CONFIGURED = os.environ.get("NOVA_DATABASE_URL", "")
BACKENDS = ["sqlite", *(["postgresql"] if CONFIGURED.startswith(("postgres", "postgresql")) else [])]
#: Rows per table (default 9): enough to have several of everything, a user with nothing, JSON with accents, NULLs…
ROWS = {"users": 8, "projects": 6, "tasks": 24, "artifacts": 14, "message_blocks": 30, "execution_events": 40}


def _alembic(url: str, *args: str, extra_env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "NOVA_DATABASE_URL": url, **(extra_env or {})}
    return subprocess.run(
        [sys.executable, "-m", "alembic", *args], cwd=ROOT, env=env, capture_output=True, text=True, timeout=300, check=False
    )


def _ok(result: subprocess.CompletedProcess[str]) -> None:
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.fixture(params=BACKENDS)
def database(request, tmp_path) -> Iterator[tuple[str, Engine]]:
    """(async URL for alembic, sync engine for the test) of an empty, dedicated database."""
    if request.param == "sqlite":
        path = tmp_path / "migration.db"
        yield f"sqlite+aiosqlite:///{path}", sa.create_engine(f"sqlite:///{path}")
        return
    base = sa.engine.make_url(CONFIGURED)
    name = f"nova_migration_{uuid.uuid4().hex[:10]}"
    admin = sa.create_engine(base.set(drivername="postgresql+psycopg", database=base.database), isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(sa.text(f'CREATE DATABASE "{name}"'))
    engine = sa.create_engine(base.set(drivername="postgresql+psycopg", database=name))
    try:
        yield base.set(drivername="postgresql+asyncpg", database=name).render_as_string(hide_password=False), engine
    finally:
        engine.dispose()
        with admin.connect() as conn:
            conn.execute(sa.text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
        admin.dispose()


# --- Synthetic data, generated from the schema of the revision under test ---------------------------------------------------


def _is_uuid(kind: Any) -> bool:
    return isinstance(kind, sa.Uuid) or type(kind).__name__.upper() == "UUID"


def _value(column: sa.Column, n: int, refs: dict[str, list[Any]], table: str) -> Any:
    """A deterministic, varied value for ``column`` of row ``n`` (one optional value in three is NULL)."""
    if column.foreign_keys:
        pool = refs.get(next(iter(column.foreign_keys)).column.table.name) or []
        if not pool or (column.nullable and n % 4 == 0):
            return None
        return pool[n % len(pool)]
    if column.nullable and n % 3 == 0 and not column.primary_key:
        return None
    kind = column.type
    if _is_uuid(kind):
        return uuid.uuid4()
    if str(kind).upper() == "CHAR(32)":  # a UUID as SQLite stores it
        return uuid.uuid4().hex
    if isinstance(kind, sa.Boolean):
        return n % 2 == 0
    if isinstance(kind, sa.Integer):
        return n % 4 if column.name in ("classification", "clearance") else n
    if isinstance(kind, sa.Float):
        return round(n * 1.37, 4)
    if isinstance(kind, sa.DateTime):
        return NOW + timedelta(hours=n, minutes=n * 7)
    if isinstance(kind, sa.JSON):
        return {"n": n, "text": f"éàü – données {table} #{n}", "nested": {"ids": [n, n + 1], "ok": n % 2 == 0}, "none": None}
    if isinstance(kind, sa.Text):
        return f"Texte synthétique {table}.{column.name} #{n}\n" + "ligne accentuée é ü ß 日本語 " * (1 + n % 5)
    length = getattr(kind, "length", None) or 40
    return f"{table}.{column.name}.{n}"[:length]


def _unique_sets(table: sa.Table) -> list[tuple[str, ...]]:
    sets = [tuple(c.name for c in table.primary_key.columns)]
    sets += [tuple(c.name for c in u.columns) for u in table.constraints if isinstance(u, sa.UniqueConstraint)]
    sets += [tuple(c.name for c in i.columns) for i in table.indexes if i.unique]
    return [s for s in sets if s]


def populate(engine: Engine) -> dict[str, int]:
    """Fill every table (in foreign-key order) with synthetic rows; returns the number of rows per table."""
    metadata = sa.MetaData()
    metadata.reflect(engine)
    refs: dict[str, list[Any]] = {}
    counts: dict[str, int] = {}
    with engine.begin() as conn:
        for table in metadata.sorted_tables:
            if table.name == "alembic_version":
                continue
            used: dict[tuple[str, ...], set[tuple[Any, ...]]] = {u: set() for u in _unique_sets(table)}
            made = 0
            for n in range(ROWS.get(table.name, 9)):
                values = {c.name: _value(c, n, refs, table.name) for c in table.columns}
                keys = {u: tuple(values[c] for c in u) for u in used}
                if any(None not in k and k in used[u] for u, k in keys.items()):
                    continue  # a unique value (or key) this table already holds
                for u, k in keys.items():
                    used[u].add(k)
                conn.execute(table.insert().values(**values))
                made += 1
            counts[table.name] = made
            pk = list(table.primary_key.columns)
            if len(pk) == 1:
                refs[table.name] = [r[0] for r in conn.execute(sa.select(pk[0]))]
    return counts


def snapshot(engine: Engine, columns: dict[str, list[str]]) -> dict[str, tuple[int, str]]:
    """(row count, hash of the listed columns of every row) per table."""
    result: dict[str, tuple[int, str]] = {}
    with engine.connect() as conn:
        for table, names in columns.items():
            quoted = ", ".join(f'"{c}"' for c in names)
            rows = sorted(
                repr(tuple(_normal(v) for v in row)) for row in conn.execute(sa.text(f'SELECT {quoted} FROM "{table}"'))
            )
            result[table] = (len(rows), hashlib.sha256("\n".join(rows).encode()).hexdigest())
    return result


def _normal(value: Any) -> Any:
    if isinstance(value, uuid.UUID):
        return value.hex
    if isinstance(value, str) and len(value) == 36 and value.count("-") == 4:
        return value.replace("-", "")
    if isinstance(value, datetime):
        return value.replace(tzinfo=None).isoformat()
    if isinstance(value, (dict, list)):
        return repr(value)
    return value


def columns_of(engine: Engine) -> dict[str, list[str]]:
    inspector = sa.inspect(engine)
    return {t: sorted(c["name"] for c in inspector.get_columns(t)) for t in inspector.get_table_names() if t != "alembic_version"}


# Tables of the Skill catalog, the learning loop and sign-in bootstrap hold no tenant data: no ``workspace_id``
NOT_SCOPED = {
    "skills",
    "skill_versions",
    "agent_policies",
    "releases",
    "training_cycles",
    "email_codes",
    "dev_identities",
    "workspaces",
}


# --- The test ---------------------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("start", ["0015", "0019"])
def test_workspaces_migration_on_a_populated_database(database, start):
    url, engine = database
    _ok(_alembic(url, "upgrade", start))
    counts = populate(engine)
    assert counts["users"] >= 5 and counts["tasks"] >= 20 and counts["artifacts"] >= 10 and counts["projects"] >= 4
    assert all(counts[t] > 0 for t in ("integration_references", "orbit_snapshot_references", "messages", "audit_events"))
    old = columns_of(engine)
    before = snapshot(engine, old)
    assert sum(n for n, _ in before.values()) > 250

    # --- up: nothing lost, nothing changed outside the new columns -----------------------------------------------------------
    _ok(_alembic(url, "upgrade", "head"))
    heads = _alembic(url, "heads")
    assert heads.stdout.count("(head)") == 1, heads.stdout  # one head only
    assert snapshot(engine, old) == before
    new = columns_of(engine)
    assert {t for t, c in new.items() if "workspace_id" in c} == set(new) - NOT_SCOPED
    assert "orion_project_id" in new["projects"] and "orion_project_id" in new["project_references"]
    default_param = _bind(engine, DEFAULT_WORKSPACE)
    with engine.connect() as conn:
        for table in set(new) - NOT_SCOPED:
            other = conn.execute(sa.text(f'SELECT count(*) FROM "{table}" WHERE workspace_id <> :ws'), {"ws": default_param})
            assert other.scalar() == 0, table  # every existing row is in the default workspace
        assert [_hex(r[0]) for r in conn.execute(sa.text("SELECT id FROM workspaces"))] == [DEFAULT_WORKSPACE.hex]
        orion = {_hex(r[0]): _hex(r[1]) for r in conn.execute(sa.text("SELECT id, orion_project_id FROM projects"))}
        assert len(orion) == counts["projects"] and len(set(orion.values())) == len(orion)
        assert all(v == uuid.uuid5(PROJECT_NAMESPACE, str(uuid.UUID(k))).hex for k, v in orion.items())
        assert conn.execute(sa.text("SELECT count(*) FROM project_references WHERE orion_project_id IS NOT NULL")).scalar() == 0
    upgraded = {t: v for t, v in snapshot(engine, new).items() if t != "workspaces"}

    # --- down: refused while workspaces would merge, then accepted; the schema and the data are back --------------------------
    with engine.begin() as conn:
        conn.execute(
            sa.text("UPDATE tasks SET workspace_id = :ws WHERE id = (SELECT id FROM tasks LIMIT 1)"),
            {"ws": _bind(engine, uuid.uuid4())},
        )
    refused = _alembic(url, "downgrade", "0019")
    assert refused.returncode != 0 and "another workspace" in refused.stderr + refused.stdout
    assert snapshot(engine, new)["tasks"][0] == counts["tasks"]  # the refusal changed nothing
    with engine.begin() as conn:
        conn.execute(sa.text("UPDATE tasks SET workspace_id = :ws"), {"ws": default_param})
    _ok(_alembic(url, "downgrade", "0019"))
    down = columns_of(engine)
    assert "workspaces" not in down and all("workspace_id" not in c and "orion_project_id" not in c for c in down.values())
    assert snapshot(engine, old) == before  # the same rows, byte for byte
    if start == "0019":
        assert down == old

    # --- up again: same rows, same new values ---------------------------------------------------------------------------------
    _ok(_alembic(url, "upgrade", "head"))
    assert {t: v for t, v in snapshot(engine, new).items() if t != "workspaces"} == upgraded

    # --- the downgrade that merges workspaces, when it is explicitly accepted -------------------------------------------------
    with engine.begin() as conn:
        conn.execute(sa.text("UPDATE tasks SET workspace_id = :ws"), {"ws": _bind(engine, uuid.uuid4())})
    _ok(_alembic(url, "downgrade", "0019", extra_env={"NOVA_ALLOW_WORKSPACE_MERGE": "1"}))
    assert snapshot(engine, old) == before


def _hex(value: Any) -> str:
    return value.hex if isinstance(value, uuid.UUID) else str(value).replace("-", "")


def _bind(engine: Engine, value: uuid.UUID) -> Any:
    """A UUID as a bound parameter of this database (hex text on SQLite, a native UUID on PostgreSQL)."""
    return value.hex if engine.dialect.name == "sqlite" else value
