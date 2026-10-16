"""Workspaces: ``workspaces`` table, ``workspace_id`` on tenant tables, ``orion_project_id`` on projects (NOV-107)

Additive and reversible (ADR 001 §8, "additif, réversible, sans changer les identifiants des données"):

* ``workspaces`` is new; the default workspace (``ORION_DEFAULT_WORKSPACE_ID``, else the fixed UUID of
  ``nova.config.DEFAULT_WORKSPACE_ID``) is inserted;
* every tenant table gets ``workspace_id`` NOT NULL with the default workspace as its server default: on PostgreSQL a
  constant default is metadata only (no table rewrite, no content rewritten); on SQLite it is a plain ADD COLUMN. Existing
  rows read the default; none of their other columns is touched. No foreign key and no index on the new column (SQLite
  cannot add a foreign key without rebuilding the table; every query is also keyed by id, user or project);
* ``projects.orion_project_id`` (unique) is filled with ``uuid5(namespace, project id)`` for the existing projects, and
  ``project_references.orion_project_id`` is empty until ORBIT reports one.

Downgrade drops what was added. It refuses to run while rows belong to another workspace than the default one (the
workspaces would silently merge) unless ``NOVA_ALLOW_WORKSPACE_MERGE=1``.

Revision ID: 0020
Revises: 0019
Create Date: 2026-10-16 10:00:00
"""

import os
import uuid
from collections.abc import Sequence
from datetime import UTC, datetime

import sqlalchemy as sa
from alembic import op

revision: str = "0020"
down_revision: str | None = "0019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: Same value as nova.services.workspaces.PROJECT_NAMESPACE (copied: a migration never imports application code that moves).
PROJECT_NAMESPACE = uuid.UUID("6f5c1a52-9f0e-4c1b-8d9a-0a1b2c3d4e5f")

#: Tables that hold tenant data (the mixin ``WorkspaceScoped`` of nova/infra/models.py).
SCOPED_TABLES = (
    "users",
    "user_preferences",
    "orbit_accounts",
    "orbit_snapshot_references",
    "figma_accounts",
    "user_llm_configs",
    "github_accounts",
    "sdlc_runs",
    "projects",
    "project_members",
    "project_references",
    "conversations",
    "messages",
    "message_blocks",
    "tasks",
    "task_steps",
    "skill_executions",
    "workflows",
    "workflow_executions",
    "artifacts",
    "artifact_versions",
    "artifact_comments",
    "context_retrieval_references",
    "orbit_events",
    "forget_requests",
    "forge_erasure_requests",
    "llm_calls",
    "tool_executions",
    "execution_events",
    "feedback",
    "integration_references",
    "forge_outbox",
    "audit_events",
    "goals",
    "routines",
    "learned_skills",
)
GUARDED = ("users", "projects", "tasks", "artifacts")  # a downgrade checks these for rows of another workspace


def _default_workspace() -> uuid.UUID:
    from nova.config import get_settings

    return get_settings().default_workspace_id


def _literal(value: uuid.UUID) -> str:
    """The default as the database stores a UUID: 32 hex characters on SQLite, the dashed form on PostgreSQL."""
    return value.hex if op.get_bind().dialect.name == "sqlite" else str(value)


def _drop_column(table: str, column: str) -> None:
    bind = op.get_bind()
    if bind.dialect.name == "sqlite" and tuple(int(p) for p in bind.exec_driver_sql("select sqlite_version()").scalar().split(".")) < (
        3,
        35,
        0,
    ):
        with op.batch_alter_table(table) as batch:  # older SQLite cannot DROP COLUMN: rebuild the table
            batch.drop_column(column)
    else:
        op.drop_column(table, column)


def upgrade() -> None:
    default = _default_workspace()
    workspaces = op.create_table(
        "workspaces",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("name", sa.String(length=200), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.bulk_insert(workspaces, [{"id": default, "name": "Default workspace", "created_at": datetime.now(UTC)}])

    for table in SCOPED_TABLES:
        op.add_column(
            table,
            sa.Column("workspace_id", sa.Uuid(), nullable=False, server_default=sa.text(f"'{_literal(default)}'")),
        )

    op.add_column("projects", sa.Column("orion_project_id", sa.Uuid(), nullable=True))
    op.add_column("project_references", sa.Column("orion_project_id", sa.Uuid(), nullable=True))
    projects = sa.table("projects", sa.column("id", sa.Uuid()), sa.column("orion_project_id", sa.Uuid()))
    bind = op.get_bind()
    ids = [row[0] for row in bind.execute(sa.select(projects.c.id))]
    if ids:
        bind.execute(
            sa.update(projects).where(projects.c.id == sa.bindparam("p_id")).values(orion_project_id=sa.bindparam("p_orion")),
            [{"p_id": i, "p_orion": uuid.uuid5(PROJECT_NAMESPACE, str(i))} for i in ids],
        )
    op.create_index("uq_projects_orion_project_id", "projects", ["orion_project_id"], unique=True)


def downgrade() -> None:
    default = _default_workspace()
    bind = op.get_bind()
    if os.environ.get("NOVA_ALLOW_WORKSPACE_MERGE") != "1":
        for name in GUARDED:
            table = sa.table(name, sa.column("workspace_id", sa.Uuid()))
            foreign = bind.execute(sa.select(sa.func.count()).select_from(table).where(table.c.workspace_id != default)).scalar()
            if foreign:
                raise RuntimeError(
                    f"{foreign} row(s) of {name} belong to another workspace than the default one: downgrading would merge "
                    "the workspaces. Set NOVA_ALLOW_WORKSPACE_MERGE=1 to do it anyway."
                )
    op.drop_index("uq_projects_orion_project_id", table_name="projects")
    _drop_column("project_references", "orion_project_id")
    _drop_column("projects", "orion_project_id")
    for table in reversed(SCOPED_TABLES):
        _drop_column(table, "workspace_id")
    op.drop_table("workspaces")
