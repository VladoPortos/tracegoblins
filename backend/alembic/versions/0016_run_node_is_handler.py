"""add run_nodes.is_handler

A notified handler that actually fired arrives as playbook_on_handler_task_start in
job_events and was previously folded into a plain task node, making it indistinguishable
in the Path Explorer. Persist a boolean so the frontend can badge fired handlers.

Revision ID: 0016
Revises: 0015
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "run_nodes",
        sa.Column("is_handler", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    # Drop the server_default now that existing rows are backfilled — the ORM supplies the
    # value on insert, matching the other boolean columns (is_conditional/changed).
    op.alter_column("run_nodes", "is_handler", server_default=None)


def downgrade() -> None:
    op.drop_column("run_nodes", "is_handler")
