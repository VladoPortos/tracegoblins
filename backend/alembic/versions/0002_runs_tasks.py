"""runs, tasks, run_raw (M2 ingestion)

Revision ID: 0002
Revises: 0001
Create Date: 2026-06-03
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("source", sa.String(length=16), nullable=False),
        sa.Column("owner_user_id", sa.Uuid(), nullable=False),
        sa.Column("team_id", sa.Uuid(), nullable=True),
        sa.Column("controller_id", sa.Uuid(), nullable=True),
        sa.Column("awx_job_id", sa.String(length=64), nullable=True),
        sa.Column("awx_job_url", sa.Text(), nullable=True),
        sa.Column("awx_user", sa.String(length=255), nullable=True),
        sa.Column("template_name", sa.Text(), nullable=True),
        sa.Column("log_time", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("host_count", sa.Integer(), nullable=False),
        sa.Column("task_count", sa.Integer(), nullable=False),
        sa.Column("warnings_count", sa.Integer(), nullable=False),
        sa.Column("recap", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["owner_user_id"], ["users.id"], name=op.f("fk_runs_owner_user_id_users"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_runs")),
        sa.UniqueConstraint("controller_id", "awx_job_id", name="uq_runs_controller_id_awx_job_id"),
    )
    op.create_index(op.f("ix_runs_owner_user_id"), "runs", ["owner_user_id"], unique=False)
    op.create_index("ix_runs_owner_created", "runs", ["owner_user_id", sa.text("created_at DESC")], unique=False)

    op.create_table(
        "tasks",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("play_name", sa.Text(), nullable=False),
        sa.Column("role", sa.Text(), nullable=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("module", sa.String(length=64), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("hosts", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("items_count", sa.Integer(), nullable=False),
        sa.Column("output", sa.Text(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("line_no", sa.Integer(), nullable=True),
        sa.Column("included_path", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["run_id"], ["runs.id"], name=op.f("fk_tasks_run_id_runs"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_tasks")),
    )
    op.create_unique_constraint("uq_tasks_run_seq", "tasks", ["run_id", "seq"])
    op.create_index("ix_tasks_run_status", "tasks", ["run_id", "status"], unique=False)

    op.create_table(
        "run_raw",
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(["run_id"], ["runs.id"], name=op.f("fk_run_raw_run_id_runs"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("run_id", name=op.f("pk_run_raw")),
    )


def downgrade() -> None:
    op.drop_table("run_raw")
    op.drop_index("ix_tasks_run_status", table_name="tasks")
    op.drop_constraint("uq_tasks_run_seq", "tasks", type_="unique")
    op.drop_table("tasks")
    op.drop_index("ix_runs_owner_created", table_name="runs")
    op.drop_index(op.f("ix_runs_owner_user_id"), table_name="runs")
    op.drop_table("runs")
