"""ORBIT snapshot reference per (user, project)

Revision ID: 0011
Revises: 0010
Create Date: 2026-10-09 20:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "orbit_snapshot_references",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("project_slug", sa.String(length=120), nullable=False),
        sa.Column("snapshot_name", sa.String(length=200), nullable=False),
        sa.Column("pinned_version", sa.Integer(), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("user_id", "project_slug"),
    )
    op.create_index("ix_orbit_snapshot_references_user_id", "orbit_snapshot_references", ["user_id"])
    op.add_column("context_retrieval_references", sa.Column("snapshot_name", sa.String(length=200), nullable=True))
    op.add_column("context_retrieval_references", sa.Column("snapshot_version", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("context_retrieval_references", "snapshot_version")
    op.drop_column("context_retrieval_references", "snapshot_name")
    op.drop_index("ix_orbit_snapshot_references_user_id", table_name="orbit_snapshot_references")
    op.drop_table("orbit_snapshot_references")
