"""runs.elapsed — total job duration in seconds from AWX (M2 polish)

AWX jobs expose a top-level `elapsed` (float seconds). Store it on the Run so
the card can surface overall duration. NULL for uploads and legacy AWX runs
(pre-0007) that pre-date the column.

Revision ID: 0007
Revises: 0006
Create Date: 2026-06-04
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("runs", sa.Column("elapsed", sa.Float(), nullable=True))


def downgrade() -> None:
    op.drop_column("runs", "elapsed")
