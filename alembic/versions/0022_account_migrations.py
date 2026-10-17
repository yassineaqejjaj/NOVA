"""Account migrations: IdP identifier and sign-in flags of the accounts the migration tool touched (NOV-113)

Additive and reversible: one new table, no existing table touched, empty until ``python -m nova.migration.accounts apply``
or ``flags`` writes to it. An account without a row signs in exactly as before. ``workspace_id`` follows the other tenant
tables (NOT NULL, the default workspace as its server default).

Revision ID: 0022
Revises: 0021
Create Date: 2026-10-17 09:00:00
"""

import uuid
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0022"
down_revision: str | None = "0021"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _default_workspace() -> uuid.UUID:
    from nova.config import get_settings

    return get_settings().default_workspace_id


def _literal(value: uuid.UUID) -> str:
    return value.hex if op.get_bind().dialect.name == "sqlite" else str(value)


def upgrade() -> None:
    op.create_table(
        "account_migrations",
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("workspace_id", sa.Uuid(), nullable=False, server_default=sa.text(f"'{_literal(_default_workspace())}'")),
        sa.Column("orion_sub", sa.String(length=255), nullable=True, unique=True),
        sa.Column("linked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("linked_batch", sa.String(length=80), nullable=True),
        sa.Column("password_login_disabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("sso_required", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("break_glass", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("flags_batch", sa.String(length=80), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("account_migrations")
