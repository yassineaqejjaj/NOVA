"""FORGE training loop: agent policies (learned lessons) and training cycles

Revision ID: 0008
Revises: 0007
Create Date: 2026-10-06 18:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSON = sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")
TS = sa.DateTime(timezone=True)


def upgrade() -> None:
    op.create_table(
        "agent_policies",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("agent", sa.String(length=20), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="candidate"),
        sa.Column("standards", JSON, nullable=False, server_default="[]"),
        sa.Column("skills", JSON, nullable=False, server_default="{}"),
        sa.Column("recommendations", JSON, nullable=False, server_default="[]"),
        sa.Column("parent_id", sa.Uuid(), nullable=True),
        sa.Column("cycle_id", sa.Uuid(), nullable=True),
        sa.Column("forge_agent_version_id", sa.String(length=64), nullable=True),
        sa.Column("forge_version_key", sa.String(length=64), nullable=True),
        sa.Column("score", sa.Float(), nullable=True),
        sa.Column("summary", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_at", TS, nullable=False),
        sa.Column("activated_at", TS, nullable=True),
        sa.Column("retired_at", TS, nullable=True),
        sa.UniqueConstraint("agent", "version"),
    )
    op.create_index("ix_agent_policies_agent_status", "agent_policies", ["agent", "status"])
    op.create_table(
        "training_cycles",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("agent", sa.String(length=20), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="queued"),
        sa.Column("trigger", sa.String(length=20), nullable=False, server_default="manual"),
        sa.Column("requested_by", sa.Uuid(), nullable=True),
        sa.Column("baseline_policy_id", sa.Uuid(), nullable=True),
        sa.Column("candidate_policy_id", sa.Uuid(), nullable=True),
        sa.Column("skills", JSON, nullable=False, server_default="[]"),
        sa.Column("baseline_runs", JSON, nullable=False, server_default="[]"),
        sa.Column("forge_experiment_id", sa.String(length=64), nullable=True),
        sa.Column("result", JSON, nullable=False, server_default="{}"),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", TS, nullable=False),
        sa.Column("updated_at", TS, nullable=False),
        sa.Column("finished_at", TS, nullable=True),
    )
    op.create_index("ix_training_cycles_agent_created", "training_cycles", ["agent", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_training_cycles_agent_created", table_name="training_cycles")
    op.drop_table("training_cycles")
    op.drop_index("ix_agent_policies_agent_status", table_name="agent_policies")
    op.drop_table("agent_policies")
