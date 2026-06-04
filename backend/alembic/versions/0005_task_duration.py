"""tasks.duration_s — per-task wall-clock seconds from AWX job_events (M4)

The job_events adapter computes per-task durations from `created` deltas; M2
persisted everything else but dropped the duration. Add a nullable column so the
Status Map can surface real durations for synced runs (NULL for stdout runs,
which have no per-task timestamps).

Revision ID: 0005
Revises: 0004
Create Date: 2026-06-04
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("tasks", sa.Column("duration_s", sa.Float(), nullable=True))


def downgrade() -> None:
    op.drop_column("tasks", "duration_s")
