"""Task.replay_of: the run a replay re-executes

Revision ID: 0014
Revises: 0013
Create Date: 2026-10-11 11:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0014"
down_revision: str | None = "0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("tasks") as batch:
        batch.add_column(sa.Column("replay_of", sa.Uuid(), nullable=True))
        batch.create_foreign_key("fk_tasks_replay_of", "tasks", ["replay_of"], ["id"], ondelete="SET NULL")
        batch.create_index("ix_tasks_replay_of", ["replay_of"])


def downgrade() -> None:
    with op.batch_alter_table("tasks") as batch:
        batch.drop_index("ix_tasks_replay_of")
        batch.drop_constraint("fk_tasks_replay_of", type_="foreignkey")
        batch.drop_column("replay_of")
