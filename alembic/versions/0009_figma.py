"""Figma account links (MCP OAuth tokens or personal access token)

Revision ID: 0009
Revises: 0008
Create Date: 2026-10-09 12:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "figma_accounts",
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("mode", sa.String(length=10), nullable=False),
        sa.Column("figma_user_id", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("handle", sa.String(length=200), nullable=False, server_default=""),
        sa.Column("token_ciphertext", sa.Text(), nullable=True),
        sa.Column("refresh_ciphertext", sa.Text(), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("scope", sa.String(length=500), nullable=False, server_default=""),
        sa.Column("linked_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("figma_accounts")
