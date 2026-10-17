"""Migration 0021 (delegation sessions) on a POPULATED database, SQLite and PostgreSQL (NOV-111).

Built at revision 0020 (workspaces), filled with synthetic rows in every table, migrated up, down and up again: the only
change is one new, empty table; nothing that existed is touched, and the downgrade gives the 0020 schema back exactly.
"""

from __future__ import annotations

import uuid

import sqlalchemy as sa

from tests.migration.test_workspaces_migration import (
    DEFAULT_WORKSPACE,
    _alembic,
    _bind,
    _ok,
    columns_of,
    database,  # noqa: F401  (the fixture)
    populate,
    snapshot,
)


def test_delegation_sessions_migration_on_a_populated_database(database):  # noqa: F811
    url, engine = database
    _ok(_alembic(url, "upgrade", "0020"))
    counts = populate(engine)
    assert counts["users"] >= 5 and counts["orbit_accounts"] > 0 and counts["tasks"] >= 20
    old = columns_of(engine)
    before = snapshot(engine, old)

    _ok(_alembic(url, "upgrade", "head"))
    heads = _alembic(url, "heads")
    assert heads.stdout.count("(head)") == 1, heads.stdout
    assert snapshot(engine, old) == before  # every existing table, byte for byte
    new = columns_of(engine)
    assert set(new) - set(old) == {"delegation_sessions"}
    assert {"user_id", "workspace_id", "access_ciphertext", "refresh_ciphertext", "links"} <= set(new["delegation_sessions"])
    with engine.connect() as conn:
        assert conn.execute(sa.text("SELECT count(*) FROM delegation_sessions")).scalar() == 0  # nothing writes it by default

    # a row takes the default workspace, and goes away with its user (ON DELETE CASCADE)
    with engine.begin() as conn:
        user_id = conn.execute(sa.text("SELECT id FROM users LIMIT 1")).scalar()
        conn.execute(
            sa.text(
                "INSERT INTO delegation_sessions (user_id, links, created_at, updated_at) VALUES (:u, '{}', now(), now())".replace(
                    "now()", "CURRENT_TIMESTAMP"
                )
            ),
            {"u": user_id},
        )
        ws = conn.execute(sa.text("SELECT workspace_id FROM delegation_sessions")).scalar()
        assert str(ws).replace("-", "") == DEFAULT_WORKSPACE.hex
        assert _bind(engine, DEFAULT_WORKSPACE)  # (same literal as the other tenant tables)

    _ok(_alembic(url, "downgrade", "0020"))
    assert columns_of(engine) == old and snapshot(engine, old) == before
    _ok(_alembic(url, "upgrade", "head"))
    assert snapshot(engine, old) == before
    assert uuid.UUID(int=0) != DEFAULT_WORKSPACE
