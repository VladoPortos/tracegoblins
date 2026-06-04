"""controller sync progress columns (M6)

Three nullable columns on awx_controllers that let the UI render a real N/M
progress bar during a manual/auto sync: sync_total (jobs to import this run,
from the AWX list `count`), sync_done (jobs processed so far), sync_current_job
(the AWX job id currently importing). All NULL between syncs.

Revision ID: 0008
Revises: 0007
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("awx_controllers", sa.Column("sync_total", sa.Integer(), nullable=True))
    op.add_column("awx_controllers", sa.Column("sync_done", sa.Integer(), nullable=True))
    op.add_column("awx_controllers", sa.Column("sync_current_job", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("awx_controllers", "sync_current_job")
    op.drop_column("awx_controllers", "sync_done")
    op.drop_column("awx_controllers", "sync_total")
