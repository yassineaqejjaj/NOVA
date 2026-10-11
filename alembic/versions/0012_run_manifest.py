"""Run manifest on tasks (ORION: one record tying a run to its agent version, snapshot, policy and model)

Revision ID: 0012
Revises: 0011
Create Date: 2026-10-11 09:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

JSON = sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")

revision: str = "0012"
down_revision: str | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("tasks", sa.Column("run_manifest", JSON, nullable=True))


def downgrade() -> None:
    op.drop_column("tasks", "run_manifest")
