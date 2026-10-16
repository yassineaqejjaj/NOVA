"""ORBIT revocation events: revoked extracts, Artifacts to review, revoked accounts, received events

Revision ID: 0018
Revises: 0017
Create Date: 2026-10-14 09:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

JSON = sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")

revision: str = "0018"
down_revision: str | None = "0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("context_retrieval_references") as batch:
        batch.add_column(sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True))
        batch.add_column(sa.Column("revoked_reason", sa.String(length=60), nullable=True))
    with op.batch_alter_table("artifacts") as batch:
        batch.add_column(sa.Column("review_requested_at", sa.DateTime(timezone=True), nullable=True))
        batch.add_column(sa.Column("review_reason", sa.String(length=60), nullable=True))
    with op.batch_alter_table("orbit_accounts") as batch:
        batch.add_column(sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True))
        batch.add_column(sa.Column("revoked_reason", sa.String(length=60), nullable=True))
    op.create_table(
        "orbit_events",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("delivery_id", sa.String(length=80), nullable=False, unique=True),
        sa.Column("type", sa.String(length=60), nullable=False),
        sa.Column("project_slug", sa.String(length=120), nullable=True),
        sa.Column("target_type", sa.String(length=20), nullable=False),
        sa.Column("target_id", sa.String(length=80), nullable=False),
        sa.Column("payload", JSON, nullable=False, server_default="{}"),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="received"),
        sa.Column("effects", JSON, nullable=False, server_default="{}"),
        sa.Column("error", sa.String(length=300), nullable=True),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("orbit_events")
    with op.batch_alter_table("orbit_accounts") as batch:
        for column in ("revoked_reason", "revoked_at"):
            batch.drop_column(column)
    with op.batch_alter_table("artifacts") as batch:
        for column in ("review_reason", "review_requested_at"):
            batch.drop_column(column)
    with op.batch_alter_table("context_retrieval_references") as batch:
        for column in ("revoked_reason", "revoked_at"):
            batch.drop_column(column)
