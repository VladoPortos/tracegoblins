"""run effective-timestamp expression index

Index on coalesce(launched_at, log_time, created_at) — the effective run timestamp
(app.services.run_time.run_when_expr) used by the analytics window scan and the
run-diff baseline lookup. Makes the coalesce(...) range/sort sargable instead of a
per-row recompute + scan of the visible set.

Revision ID: 0012
Revises: 0011
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "ix_runs_when",
        "runs",
        [sa.text("coalesce(launched_at, log_time, created_at)")],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_runs_when", table_name="runs")
