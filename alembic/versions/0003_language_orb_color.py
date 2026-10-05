"""interface language and orb color preferences

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-03 23:30:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("user_preferences", sa.Column("language", sa.String(length=5), nullable=True))
    op.add_column("user_preferences", sa.Column("orb_color", sa.String(length=20), nullable=False, server_default="coral"))


def downgrade() -> None:
    op.drop_column("user_preferences", "orb_color")
    op.drop_column("user_preferences", "language")
