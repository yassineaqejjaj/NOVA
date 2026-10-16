"""ORBIT link health: last exchange and agent-key fallback on orbit_accounts

Revision ID: 0016
Revises: 0015
Create Date: 2026-10-13 12:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0016"
down_revision: str | None = "0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("orbit_accounts") as batch:
        batch.add_column(sa.Column("last_success_at", sa.DateTime(timezone=True), nullable=True))
        batch.add_column(sa.Column("last_error_at", sa.DateTime(timezone=True), nullable=True))
        batch.add_column(sa.Column("last_error", sa.String(length=300), nullable=True))
        batch.add_column(sa.Column("agent_fallback_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("orbit_accounts") as batch:
        for column in ("agent_fallback_at", "last_error", "last_error_at", "last_success_at"):
            batch.drop_column(column)
