"""Engineering: user LLM keys, GitHub accounts, SDLC runs

Revision ID: 0010
Revises: 0009
Create Date: 2026-10-09 18:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSON = sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")


def upgrade() -> None:
    op.create_table(
        "user_llm_configs",
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("provider", sa.String(length=30), nullable=False),
        sa.Column("model", sa.String(length=120), nullable=False),
        sa.Column("base_url", sa.String(length=500), nullable=False, server_default=""),
        sa.Column("key_ciphertext", sa.Text(), nullable=False),
        sa.Column("key_hint", sa.String(length=12), nullable=False, server_default=""),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "github_accounts",
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("login", sa.String(length=100), nullable=False, server_default=""),
        sa.Column("token_ciphertext", sa.Text(), nullable=False),
        sa.Column("scopes", sa.String(length=500), nullable=False, server_default=""),
        sa.Column("linked_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "sdlc_runs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("project_id", sa.Uuid(), sa.ForeignKey("projects.id", ondelete="SET NULL"), nullable=True),
        sa.Column("kind", sa.String(length=12), nullable=False, server_default="feature"),
        sa.Column("title", sa.String(length=300), nullable=False),
        sa.Column("goal", sa.Text(), nullable=False, server_default=""),
        sa.Column("repo", sa.String(length=200), nullable=False),
        sa.Column("base_branch", sa.String(length=200), nullable=False, server_default=""),
        sa.Column("branch", sa.String(length=250), nullable=False, server_default=""),
        sa.Column("autonomy", sa.String(length=12), nullable=False, server_default="guided"),
        sa.Column("auto_merge", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("deploy_hook_ciphertext", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=14), nullable=False, server_default="queued"),
        sa.Column("stage", sa.String(length=20), nullable=False, server_default="spec"),
        sa.Column("stages", JSON, nullable=False, server_default="[]"),
        sa.Column("log", JSON, nullable=False, server_default="[]"),
        sa.Column("context", JSON, nullable=False, server_default="{}"),
        sa.Column("issue_url", sa.String(length=500), nullable=False, server_default=""),
        sa.Column("pr_number", sa.Integer(), nullable=True),
        sa.Column("pr_url", sa.String(length=500), nullable=False, server_default=""),
        sa.Column("head_sha", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("merge_sha", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("release_url", sa.String(length=500), nullable=False, server_default=""),
        sa.Column("gate", sa.String(length=20), nullable=True),
        sa.Column("lease_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("usage", JSON, nullable=False, server_default="{}"),
        sa.Column("model", sa.String(length=120), nullable=False, server_default=""),
        sa.Column("error", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_sdlc_runs_status", "sdlc_runs", ["status"])
    op.create_index("ix_sdlc_runs_user_created", "sdlc_runs", ["user_id", "created_at"])


def downgrade() -> None:
    op.drop_table("sdlc_runs")
    op.drop_table("github_accounts")
    op.drop_table("user_llm_configs")
