"""drop tasks.module: reserved as a placeholder in M2, never populated or read

Revision ID: 0011
Revises: 0010
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_column("tasks", "module")


def downgrade() -> None:
    op.add_column(
        "tasks",
        sa.Column("module", sa.String(length=64), nullable=True),
    )
