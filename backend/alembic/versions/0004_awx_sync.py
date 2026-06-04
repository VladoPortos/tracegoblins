"""awx_controllers, controller_teams, runs AWX columns + nullable owner_user_id (M4 AWX sync)

Revision ID: 0004
Revises: 0003
Create Date: 2026-06-04
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Own the pg_trgm extension (M2/M3 never created it).
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")

    # --- Table: awx_controllers ---
    op.create_table(
        "awx_controllers",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("base_url", sa.Text(), nullable=False),
        sa.Column("auth_token_encrypted", sa.Text(), nullable=False),
        sa.Column("verify_ssl", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("sync_mode", sa.String(length=8), server_default="manual", nullable=False),
        sa.Column("sync_interval_minutes", sa.Integer(), nullable=True),
        sa.Column("last_synced_job_id", sa.Integer(), nullable=True),
        sa.Column("last_sync_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_sync_status", sa.String(length=8), server_default="never", nullable=False),
        sa.Column("last_sync_error", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=12), server_default="unconfigured", nullable=False),
        sa.Column("created_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"], ["users.id"],
            name=op.f("fk_awx_controllers_created_by_user_id_users"), ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_awx_controllers")),
    )
    op.create_unique_constraint("uq_awx_controllers_name", "awx_controllers", ["name"])

    # --- Table: controller_teams (org-aware) ---
    op.create_table(
        "controller_teams",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("controller_id", sa.Uuid(), nullable=False),
        sa.Column("team_id", sa.Uuid(), nullable=False),
        sa.Column("awx_organization_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["controller_id"], ["awx_controllers.id"],
            name=op.f("fk_controller_teams_controller_id_awx_controllers"), ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["team_id"], ["teams.id"],
            name=op.f("fk_controller_teams_team_id_teams"), ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_controller_teams")),
    )
    # Lookup indexes
    op.create_index("ix_controller_teams_team", "controller_teams", ["team_id"])
    op.create_index("ix_controller_teams_controller", "controller_teams", ["controller_id"])
    # NULL-distinct partial unique indexes (plain UNIQUE on 3-col would allow multiple NULL rows)
    op.create_index(
        "uq_controller_teams_specific", "controller_teams",
        ["controller_id", "team_id", "awx_organization_id"],
        unique=True, postgresql_where=sa.text("awx_organization_id IS NOT NULL"),
    )
    op.create_index(
        "uq_controller_teams_allorgs", "controller_teams",
        ["controller_id", "team_id"],
        unique=True, postgresql_where=sa.text("awx_organization_id IS NULL"),
    )

    # --- runs: additive nullable AWX columns ---
    op.add_column("runs", sa.Column("awx_organization_id", sa.Integer(), nullable=True))
    op.add_column("runs", sa.Column("awx_organization_name", sa.Text(), nullable=True))
    op.add_column("runs", sa.Column("awx_launch_type", sa.String(length=16), nullable=True))
    op.add_column("runs", sa.Column("awx_workflow_name", sa.Text(), nullable=True))

    # Widen owner_user_id to nullable — AWX runs are owner-less (spec §3).
    # Safe: existing rows are all uploads with owner set; only AWX rows ever write NULL.
    op.alter_column("runs", "owner_user_id", existing_type=sa.Uuid(), nullable=True)

    # Promote bare-Uuid runs.controller_id (added in 0002) to a real FK.
    op.create_foreign_key(
        op.f("fk_runs_controller_id_awx_controllers"), "runs", "awx_controllers",
        ["controller_id"], ["id"], ondelete="CASCADE",
    )

    # Filter / scale indexes (D8). created_at DESC matches the stable list order.
    op.create_index("ix_runs_controller_created", "runs", ["controller_id", sa.text("created_at DESC")])
    op.create_index("ix_runs_org", "runs", ["awx_organization_id"])
    op.create_index("ix_runs_status", "runs", ["status"])
    op.create_index("ix_runs_awx_user", "runs", ["awx_user"])
    op.create_index(
        "ix_runs_template_trgm", "runs", ["template_name"],
        postgresql_using="gin", postgresql_ops={"template_name": "gin_trgm_ops"},
    )


def downgrade() -> None:
    # Drop filter indexes first
    op.drop_index("ix_runs_template_trgm", table_name="runs")
    op.drop_index("ix_runs_awx_user", table_name="runs")
    op.drop_index("ix_runs_status", table_name="runs")
    op.drop_index("ix_runs_org", table_name="runs")
    op.drop_index("ix_runs_controller_created", table_name="runs")

    # Drop the FK (promoted in upgrade)
    op.drop_constraint(op.f("fk_runs_controller_id_awx_controllers"), "runs", type_="foreignkey")

    # Re-narrow owner_user_id — but first remove AWX rows that have owner_user_id=NULL;
    # otherwise the NOT NULL constraint re-add fails.
    op.execute("DELETE FROM runs WHERE source='awx'")
    op.alter_column("runs", "owner_user_id", existing_type=sa.Uuid(), nullable=False)

    # Drop the additive AWX columns
    op.drop_column("runs", "awx_workflow_name")
    op.drop_column("runs", "awx_launch_type")
    op.drop_column("runs", "awx_organization_name")
    op.drop_column("runs", "awx_organization_id")

    # Drop controller_teams (indexes first)
    op.drop_index("uq_controller_teams_allorgs", table_name="controller_teams")
    op.drop_index("uq_controller_teams_specific", table_name="controller_teams")
    op.drop_index("ix_controller_teams_controller", table_name="controller_teams")
    op.drop_index("ix_controller_teams_team", table_name="controller_teams")
    op.drop_table("controller_teams")

    # Drop awx_controllers (unique constraint first)
    op.drop_constraint("uq_awx_controllers_name", "awx_controllers", type_="unique")
    op.drop_table("awx_controllers")

    # Do NOT drop pg_trgm — it may be shared by other objects.
