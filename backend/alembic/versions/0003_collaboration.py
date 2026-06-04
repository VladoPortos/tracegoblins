"""run_shares, annotations, comments, notifications + runs team index (M3 collaboration)

Revision ID: 0003
Revises: 0002
Create Date: 2026-06-03
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # runs.team_id already exists (nullable, from 0002) — add the Team-tab index AND
    # activate the FK to teams (M2 left it a bare Uuid). ON DELETE SET NULL so deleting
    # a team nulls its runs' team_id (fails closed) instead of dangling.
    op.create_index(
        "ix_runs_team_created", "runs", ["team_id", sa.text("created_at DESC")], unique=False
    )
    op.create_foreign_key(
        "fk_runs_team_id_teams", "runs", "teams", ["team_id"], ["id"], ondelete="SET NULL"
    )

    op.create_table(
        "run_shares",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("shared_with_user_id", sa.Uuid(), nullable=True),
        sa.Column("shared_with_team_id", sa.Uuid(), nullable=True),
        sa.Column("permission", sa.String(length=16), nullable=False),
        sa.Column("shared_by_user_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "(shared_with_user_id IS NOT NULL) <> (shared_with_team_id IS NOT NULL)",
            name="exactly_one_target",
        ),
        sa.ForeignKeyConstraint(["run_id"], ["runs.id"], name=op.f("fk_run_shares_run_id_runs"), ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["shared_with_user_id"], ["users.id"], name=op.f("fk_run_shares_shared_with_user_id_users"), ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["shared_with_team_id"], ["teams.id"], name=op.f("fk_run_shares_shared_with_team_id_teams"), ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["shared_by_user_id"], ["users.id"], name=op.f("fk_run_shares_shared_by_user_id_users"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_run_shares")),
    )
    op.create_index("uq_run_shares_user", "run_shares", ["run_id", "shared_with_user_id"],
                    unique=True, postgresql_where=sa.text("shared_with_user_id IS NOT NULL"))
    op.create_index("uq_run_shares_team", "run_shares", ["run_id", "shared_with_team_id"],
                    unique=True, postgresql_where=sa.text("shared_with_team_id IS NOT NULL"))
    op.create_index("ix_run_shares_user", "run_shares", ["shared_with_user_id"], unique=False)
    op.create_index("ix_run_shares_team", "run_shares", ["shared_with_team_id"], unique=False)

    op.create_table(
        "annotations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("task_seq", sa.Integer(), nullable=False),
        sa.Column("author_user_id", sa.Uuid(), nullable=False),
        sa.Column("note", sa.Text(), nullable=False),
        sa.Column("tags", postgresql.ARRAY(sa.Text()), nullable=False),
        sa.Column("links", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("resolved", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["run_id"], ["runs.id"], name=op.f("fk_annotations_run_id_runs"), ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["author_user_id"], ["users.id"], name=op.f("fk_annotations_author_user_id_users"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_annotations")),
    )
    op.create_index("ix_annotations_run_task", "annotations", ["run_id", "task_seq"], unique=False)

    op.create_table(
        "comments",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("task_seq", sa.Integer(), nullable=True),
        sa.Column("annotation_id", sa.Uuid(), nullable=True),
        sa.Column("parent_id", sa.Uuid(), nullable=True),
        sa.Column("author_user_id", sa.Uuid(), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("mentions", postgresql.ARRAY(sa.Uuid()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("edited_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["run_id"], ["runs.id"], name=op.f("fk_comments_run_id_runs"), ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["annotation_id"], ["annotations.id"], name=op.f("fk_comments_annotation_id_annotations"), ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["parent_id"], ["comments.id"], name=op.f("fk_comments_parent_id_comments"), ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["author_user_id"], ["users.id"], name=op.f("fk_comments_author_user_id_users"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_comments")),
    )
    op.create_index("ix_comments_run_task", "comments", ["run_id", "task_seq"], unique=False)
    op.create_index("ix_comments_parent", "comments", ["parent_id"], unique=False)

    op.create_table(
        "notifications",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("type", sa.String(length=16), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=True),
        sa.Column("comment_id", sa.Uuid(), nullable=True),
        sa.Column("actor_user_id", sa.Uuid(), nullable=True),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name=op.f("fk_notifications_user_id_users"), ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["run_id"], ["runs.id"], name=op.f("fk_notifications_run_id_runs"), ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["comment_id"], ["comments.id"], name=op.f("fk_notifications_comment_id_comments"), ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["actor_user_id"], ["users.id"], name=op.f("fk_notifications_actor_user_id_users"), ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_notifications")),
    )
    op.create_index("ix_notifications_user_read", "notifications", ["user_id", "read_at"], unique=False)
    op.create_index("ix_notifications_user_created", "notifications", ["user_id", sa.text("created_at DESC")], unique=False)


def downgrade() -> None:
    op.drop_index("ix_notifications_user_created", table_name="notifications")
    op.drop_index("ix_notifications_user_read", table_name="notifications")
    op.drop_table("notifications")
    op.drop_index("ix_comments_parent", table_name="comments")
    op.drop_index("ix_comments_run_task", table_name="comments")
    op.drop_table("comments")
    op.drop_index("ix_annotations_run_task", table_name="annotations")
    op.drop_table("annotations")
    op.drop_index("ix_run_shares_team", table_name="run_shares")
    op.drop_index("ix_run_shares_user", table_name="run_shares")
    op.drop_index("uq_run_shares_team", table_name="run_shares")
    op.drop_index("uq_run_shares_user", table_name="run_shares")
    op.drop_table("run_shares")
    op.drop_constraint("fk_runs_team_id_teams", "runs", type_="foreignkey")
    op.drop_index("ix_runs_team_created", table_name="runs")
