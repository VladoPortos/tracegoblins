"""projects table + runs(controller_id, project_id) link index (Projects subsystem M2)

Revision ID: 0014
Revises: 0013
Create Date: 2026-06-25
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0014"
down_revision: str | None = "0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "projects",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("controller_id", sa.Uuid(), nullable=False),
        sa.Column("awx_project_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("scm_type", sa.String(length=16), server_default="", nullable=False),
        sa.Column("scm_url", sa.Text(), nullable=True),
        sa.Column("scm_branch", sa.Text(), nullable=True),
        sa.Column("scm_revision", sa.Text(), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("organization_id", sa.Integer(), nullable=True),
        sa.Column("organization_name", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=16), server_default="unlinked", nullable=False),
        sa.Column("git_url_override", sa.Text(), nullable=True),
        sa.Column("git_auth_type", sa.String(length=8), nullable=True),
        sa.Column("git_username", sa.Text(), nullable=True),
        sa.Column("git_secret_encrypted", sa.Text(), nullable=True),
        sa.Column("last_clone_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_clone_error", sa.Text(), nullable=True),
        sa.Column("clone_size_bytes", sa.BigInteger(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["controller_id"], ["awx_controllers.id"],
                                name=op.f("fk_projects_controller_id_awx_controllers"),
                                ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_projects")),
        sa.UniqueConstraint("controller_id", "awx_project_id",
                            name="uq_projects_controller_awx_project"),
    )
    op.create_index("ix_projects_organization_id", "projects", ["organization_id"])
    op.create_index("ix_runs_controller_project", "runs", ["controller_id", "project_id"])


def downgrade() -> None:
    op.drop_index("ix_runs_controller_project", table_name="runs")
    op.drop_index("ix_projects_organization_id", table_name="projects")
    op.drop_table("projects")
