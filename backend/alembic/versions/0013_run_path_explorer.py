# backend/alembic/versions/0013_run_path_explorer.py
"""run_nodes, run_node_results, runs path-input columns (Run Path Explorer M1)

Revision ID: 0013
Revises: 0012
Create Date: 2026-06-25
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0013"
down_revision: str | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("runs", sa.Column("project_id", sa.Integer(), nullable=True))
    op.add_column("runs", sa.Column("project_name", sa.Text(), nullable=True))
    op.add_column("runs", sa.Column("job_template_id", sa.Integer(), nullable=True))
    op.add_column("runs", sa.Column("scm_revision", sa.Text(), nullable=True))
    op.add_column("runs", sa.Column("awx_limit", sa.Text(), nullable=True))
    op.add_column("runs", sa.Column("extra_vars", postgresql.JSONB(), nullable=True))
    op.add_column("runs", sa.Column("survey", postgresql.JSONB(), nullable=True))

    op.create_table(
        "run_nodes",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("node_id", sa.Text(), nullable=False),
        sa.Column("parent_node_id", sa.Text(), nullable=True),
        sa.Column("counter", sa.Integer(), nullable=False),
        sa.Column("depth", sa.Integer(), nullable=False),
        sa.Column("node_type", sa.String(length=16), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("action", sa.Text(), nullable=True),
        sa.Column("task_path", sa.Text(), nullable=True),
        sa.Column("ansible_uuid", sa.Text(), nullable=True),
        sa.Column("is_conditional", sa.Boolean(), nullable=False),
        sa.Column("when_expr", sa.Text(), nullable=True),
        sa.Column("loop_var", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("changed", sa.Boolean(), nullable=False),
        sa.Column("host_count", sa.Integer(), nullable=False),
        sa.Column("item_count", sa.Integer(), nullable=False),
        sa.Column("child_count", sa.Integer(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("duration_s", sa.Float(), nullable=True),
        sa.Column("args", postgresql.JSONB(), nullable=True),
        sa.ForeignKeyConstraint(["run_id"], ["runs.id"],
                                name=op.f("fk_run_nodes_run_id_runs"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_run_nodes")),
    )
    op.create_unique_constraint("uq_run_nodes_run_node", "run_nodes", ["run_id", "node_id"])
    op.create_index("ix_run_nodes_run_parent", "run_nodes", ["run_id", "parent_node_id"])

    op.create_table(
        "run_node_results",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("node_id", sa.Text(), nullable=False),
        sa.Column("host", sa.Text(), nullable=False),
        sa.Column("item_index", sa.Integer(), nullable=True),
        sa.Column("item_value", postgresql.JSONB(), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("changed", sa.Boolean(), nullable=False),
        sa.Column("result", postgresql.JSONB(), nullable=True),
        sa.Column("skip_reason", sa.Text(), nullable=True),
        sa.Column("false_condition", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("duration_s", sa.Float(), nullable=True),
        sa.ForeignKeyConstraint(["run_id"], ["runs.id"],
                                name=op.f("fk_run_node_results_run_id_runs"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_run_node_results")),
    )
    op.create_index("ix_run_node_results_run_node", "run_node_results", ["run_id", "node_id"])


def downgrade() -> None:
    op.drop_index("ix_run_node_results_run_node", table_name="run_node_results")
    op.drop_table("run_node_results")
    op.drop_index("ix_run_nodes_run_parent", table_name="run_nodes")
    op.drop_constraint("uq_run_nodes_run_node", "run_nodes", type_="unique")
    op.drop_table("run_nodes")
    for col in ("survey", "extra_vars", "awx_limit", "scm_revision",
                "job_template_id", "project_name", "project_id"):
        op.drop_column("runs", col)
