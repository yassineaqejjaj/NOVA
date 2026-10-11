"""Releases: canary, approval and rollback of learned policies; Task.release_id

Revision ID: 0015
Revises: 0014
Create Date: 2026-10-11 12:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

JSON = sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")

revision: str = "0015"
down_revision: str | None = "0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "releases",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("agent", sa.String(length=20), nullable=False),
        sa.Column("policy_id", sa.Uuid(), sa.ForeignKey("agent_policies.id", ondelete="CASCADE"), nullable=False),
        sa.Column("baseline_policy_id", sa.Uuid(), nullable=True),
        sa.Column("label", sa.String(length=40), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="canary"),
        sa.Column("canary_percent", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("evidence", JSON, nullable=False, server_default="{}"),
        sa.Column("reason", sa.Text(), nullable=False, server_default=""),
        sa.Column("decided_by", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("canary_started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_releases_agent_status", "releases", ["agent", "status"])
    with op.batch_alter_table("tasks") as batch:
        batch.add_column(sa.Column("release_id", sa.Uuid(), nullable=True))
        batch.create_index("ix_tasks_release_id", ["release_id"])


def downgrade() -> None:
    with op.batch_alter_table("tasks") as batch:
        batch.drop_index("ix_tasks_release_id")
        batch.drop_column("release_id")
    op.drop_index("ix_releases_agent_status", table_name="releases")
    op.drop_table("releases")
