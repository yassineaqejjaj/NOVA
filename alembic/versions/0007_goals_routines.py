"""NOVA as a team member: goals, routines, learned skills, action permissions, Today visits, Teach NOVA

Revision ID: 0007
Revises: 0006
Create Date: 2026-10-06 09:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSON = sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")
TS = sa.DateTime(timezone=True)


def upgrade() -> None:
    op.create_table(
        "goals",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("project_id", sa.Uuid(), sa.ForeignKey("projects.id", ondelete="SET NULL"), nullable=True),
        sa.Column("conversation_id", sa.Uuid(), sa.ForeignKey("conversations.id", ondelete="SET NULL"), nullable=True),
        sa.Column("title", sa.String(length=300), nullable=False),
        sa.Column("outcome", sa.Text(), nullable=False, server_default=""),
        sa.Column("due_date", TS, nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="planning"),
        sa.Column("autonomy", sa.String(length=30), nullable=False, server_default="execute_with_approval"),
        sa.Column("lang", sa.String(length=5), nullable=False, server_default="en"),
        sa.Column("plan", JSON, nullable=False, server_default="{}"),
        sa.Column("created_at", TS, nullable=False),
        sa.Column("updated_at", TS, nullable=False),
        sa.Column("completed_at", TS, nullable=True),
    )
    op.create_index("ix_goals_user_status", "goals", ["user_id", "status"])
    op.create_table(
        "routines",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("project_id", sa.Uuid(), sa.ForeignKey("projects.id", ondelete="SET NULL"), nullable=True),
        sa.Column("conversation_id", sa.Uuid(), sa.ForeignKey("conversations.id", ondelete="SET NULL"), nullable=True),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("instructions", sa.Text(), nullable=False),
        sa.Column("skill_ids", JSON, nullable=False, server_default="[]"),
        sa.Column("template", sa.String(length=60), nullable=True),
        sa.Column("schedule", JSON, nullable=False, server_default="{}"),
        sa.Column("autonomy", sa.String(length=30), nullable=False, server_default="execute_automatically"),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("next_run_at", TS, nullable=True),
        sa.Column("last_run_at", TS, nullable=True),
        sa.Column("last_task_id", sa.Uuid(), nullable=True),
        sa.Column("runs", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", TS, nullable=False),
    )
    op.create_index("ix_routines_next_run_at", "routines", ["next_run_at"])
    op.create_table(
        "learned_skills",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("slug", sa.String(length=80), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("steps", JSON, nullable=False, server_default="[]"),
        sa.Column("source", JSON, nullable=False, server_default="{}"),
        sa.Column("lang", sa.String(length=5), nullable=False, server_default="en"),
        sa.Column("uses", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", TS, nullable=False),
        sa.UniqueConstraint("user_id", "slug"),
    )
    op.add_column("user_preferences", sa.Column("action_permissions", JSON, nullable=False, server_default="{}"))
    op.add_column("user_preferences", sa.Column("today_seen_at", TS, nullable=True))
    op.add_column("user_preferences", sa.Column("teaching_since", TS, nullable=True))


def downgrade() -> None:
    op.drop_column("user_preferences", "teaching_since")
    op.drop_column("user_preferences", "today_seen_at")
    op.drop_column("user_preferences", "action_permissions")
    op.drop_table("learned_skills")
    op.drop_index("ix_routines_next_run_at", table_name="routines")
    op.drop_table("routines")
    op.drop_index("ix_goals_user_status", table_name="goals")
    op.drop_table("goals")
