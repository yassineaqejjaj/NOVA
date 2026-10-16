"""Delegation sessions: the user's own OIDC tokens (encrypted) kept for token exchange (NOV-111)

Additive and reversible: one new table, no existing table touched. Empty until ``NOVA_DELEGATION_MODE=token_exchange``
stores a session at sign-in; with the default mode nothing writes to it. ``workspace_id`` follows the other tenant tables
(NOT NULL, the default workspace as its server default).

Revision ID: 0021
Revises: 0020
Create Date: 2026-10-16 13:00:00
"""

import uuid
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

JSON = sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")

revision: str = "0021"
down_revision: str | None = "0020"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _default_workspace() -> uuid.UUID:
    from nova.config import get_settings

    return get_settings().default_workspace_id


def _literal(value: uuid.UUID) -> str:
    return value.hex if op.get_bind().dialect.name == "sqlite" else str(value)


def upgrade() -> None:
    op.create_table(
        "delegation_sessions",
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("workspace_id", sa.Uuid(), nullable=False, server_default=sa.text(f"'{_literal(_default_workspace())}'")),
        sa.Column("access_ciphertext", sa.Text(), nullable=True),
        sa.Column("access_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("refresh_ciphertext", sa.Text(), nullable=True),
        sa.Column("refresh_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("links", JSON, nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("delegation_sessions")
