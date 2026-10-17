"""Migration 0022 (account migrations) on a POPULATED database, SQLite and PostgreSQL (NOV-113).

Built at revision 0021, filled with synthetic rows in every table, migrated to head, down and up again: the only change is one
new, empty table, every existing row is byte for byte the same, and one Alembic head remains.
"""

from __future__ import annotations

import sqlalchemy as sa

from tests.migration.test_workspaces_migration import (
    DEFAULT_WORKSPACE,
    _alembic,
    _ok,
    columns_of,
    database,  # noqa: F401  (the fixture)
    populate,
    snapshot,
)


def test_account_migrations_migration_on_a_populated_database(database):  # noqa: F811
    url, engine = database
    _ok(_alembic(url, "upgrade", "0021"))
    counts = populate(engine)
    assert counts["users"] >= 5 and counts["delegation_sessions"] > 0 and counts["orbit_accounts"] > 0
    old = columns_of(engine)
    before = snapshot(engine, old)

    _ok(_alembic(url, "upgrade", "head"))
    heads = _alembic(url, "heads")
    assert heads.stdout.count("(head)") == 1, heads.stdout
    assert snapshot(engine, old) == before  # every existing table, byte for byte
    new = columns_of(engine)
    assert set(new) - set(old) == {"account_migrations"}
    assert {"user_id", "workspace_id", "orion_sub", "password_login_disabled", "sso_required", "break_glass"} <= set(
        new["account_migrations"]
    )
    with engine.connect() as conn:
        assert conn.execute(sa.text("SELECT count(*) FROM account_migrations")).scalar() == 0  # nobody is touched by default

    with engine.begin() as conn:  # defaults: a row closes nothing, and takes the default workspace
        user_id = conn.execute(sa.text("SELECT id FROM users LIMIT 1")).scalar()
        conn.execute(
            sa.text("INSERT INTO account_migrations (user_id, updated_at) VALUES (:u, CURRENT_TIMESTAMP)"), {"u": user_id}
        )
        row = conn.execute(
            sa.text("SELECT workspace_id, password_login_disabled, sso_required, break_glass, orion_sub FROM account_migrations")
        ).one()
        assert str(row[0]).replace("-", "") == DEFAULT_WORKSPACE.hex
        assert not row[1] and not row[2] and not row[3] and row[4] is None

    _ok(_alembic(url, "downgrade", "0021"))
    assert columns_of(engine) == old and snapshot(engine, old) == before
    _ok(_alembic(url, "upgrade", "head"))
    assert snapshot(engine, old) == before
