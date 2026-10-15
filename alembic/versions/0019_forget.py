"""Forgetting and propagated retention: forget requests, FORGE erasure requests

Revision ID: 0019
Revises: 0018
Create Date: 2026-10-14 14:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

JSON = sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")

revision: str = "0019"
down_revision: str | None = "0018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "forget_requests",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("scope", sa.String(length=10), nullable=False),
        sa.Column("target", sa.String(length=120), nullable=False),
        sa.Column("origin", sa.String(length=20), nullable=False, server_default="admin"),
        sa.Column("actor_id", sa.Uuid(), nullable=True),
        sa.Column("status", sa.String(length=10), nullable=False, server_default="completed"),
        sa.Column("effects", JSON, nullable=False, server_default="{}"),
        sa.Column("error", sa.String(length=300), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "forge_erasure_requests",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("run_id", sa.String(length=200), nullable=False, unique=True),
        sa.Column("task_id", sa.Uuid(), nullable=True),
        sa.Column("status", sa.String(length=15), nullable=False, server_default="pending"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_error", sa.String(length=300), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("acknowledged_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("forge_erasure_requests")
    op.drop_table("forget_requests")
