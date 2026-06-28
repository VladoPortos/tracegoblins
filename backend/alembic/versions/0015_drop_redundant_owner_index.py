"""drop redundant single-column index on runs.owner_user_id

ix_runs_owner_user_id is fully covered by the composite ix_runs_owner_created
(owner_user_id, created_at DESC) via its leftmost prefix, so the single-column
index is redundant for lookups/joins (RUNS1). Dropping it saves write/space cost.

Revision ID: 0015
Revises: 0014
"""
from __future__ import annotations

from alembic import op

revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_index("ix_runs_owner_user_id", table_name="runs")


def downgrade() -> None:
    op.create_index("ix_runs_owner_user_id", "runs", ["owner_user_id"], unique=False)
