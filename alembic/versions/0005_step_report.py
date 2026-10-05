"""task step report: goal set by NOVA, Validation agent result and handoff to the next sub-agent

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-05 16:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    report = sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")
    op.add_column("task_steps", sa.Column("report", report, nullable=True))


def downgrade() -> None:
    op.drop_column("task_steps", "report")
