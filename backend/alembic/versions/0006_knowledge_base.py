"""kb_signatures + kb_occurrences (M5 Knowledge Base)

Two tables: kb_signatures (team-scoped; team_id NULL = admin-promotable global
tier; representative_text is the pg_trgm fuzzy-match target) and kb_occurrences
(deduped per (signature, run, task_seq)). pg_trgm already exists (created by
0004) — do NOT re-create or drop it.

Revision ID: 0006
Revises: 0005
Create Date: 2026-06-04
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # --- Table: kb_signatures ---
    op.create_table(
        "kb_signatures",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("team_id", sa.Uuid(), nullable=True),  # NULL = global tier
        sa.Column("signature_key", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("category", sa.Text(), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("is_problem", sa.Text(), nullable=True),
        sa.Column("where_it_lives", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=12), server_default="needs-fix", nullable=False),
        sa.Column("representative_text", sa.Text(), nullable=False),
        sa.Column("match_patterns", postgresql.JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("links", postgresql.JSONB(), server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column("created_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["team_id"], ["teams.id"],
            name=op.f("fk_kb_signatures_team_id_teams"), ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"], ["users.id"],
            name=op.f("fk_kb_signatures_created_by_user_id_users"), ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_kb_signatures")),
    )
    # NULL-distinct partial-unique pair (the 0004 controller_teams trick): one entry per
    # (team, key) for team rows, and exactly one global row per key (team_id NULL).
    op.create_index(
        "uq_kb_signatures_team_key", "kb_signatures", ["team_id", "signature_key"],
        unique=True, postgresql_where=sa.text("team_id IS NOT NULL"),
    )
    op.create_index(
        "uq_kb_signatures_global_key", "kb_signatures", ["signature_key"],
        unique=True, postgresql_where=sa.text("team_id IS NULL"),
    )
    op.create_index("ix_kb_signatures_team", "kb_signatures", ["team_id"])
    op.create_index("ix_kb_signatures_status", "kb_signatures", ["status"])
    op.create_index(
        "ix_kb_signatures_rep_trgm", "kb_signatures", ["representative_text"],
        postgresql_using="gin", postgresql_ops={"representative_text": "gin_trgm_ops"},
    )

    # --- Table: kb_occurrences ---
    op.create_table(
        "kb_occurrences",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("signature_id", sa.Uuid(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("task_seq", sa.Integer(), nullable=False),
        sa.Column("host", sa.Text(), nullable=True),
        sa.Column("matched_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["signature_id"], ["kb_signatures.id"],
            name=op.f("fk_kb_occurrences_signature_id_kb_signatures"), ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["run_id"], ["runs.id"],
            name=op.f("fk_kb_occurrences_run_id_runs"), ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_kb_occurrences")),
    )
    op.create_unique_constraint(
        "uq_kb_occurrences_sig_run_seq", "kb_occurrences",
        ["signature_id", "run_id", "task_seq"],
    )
    op.create_index("ix_kb_occurrences_signature", "kb_occurrences", ["signature_id"])
    op.create_index("ix_kb_occurrences_run", "kb_occurrences", ["run_id"])


def downgrade() -> None:
    # Drop kb_occurrences first (indexes + unique constraint), then kb_signatures (indexes).
    op.drop_index("ix_kb_occurrences_run", table_name="kb_occurrences")
    op.drop_index("ix_kb_occurrences_signature", table_name="kb_occurrences")
    op.drop_constraint("uq_kb_occurrences_sig_run_seq", "kb_occurrences", type_="unique")
    op.drop_table("kb_occurrences")

    op.drop_index("ix_kb_signatures_rep_trgm", table_name="kb_signatures")
    op.drop_index("ix_kb_signatures_status", table_name="kb_signatures")
    op.drop_index("ix_kb_signatures_team", table_name="kb_signatures")
    op.drop_index("uq_kb_signatures_global_key", table_name="kb_signatures")
    op.drop_index("uq_kb_signatures_team_key", table_name="kb_signatures")
    op.drop_table("kb_signatures")

    # Do NOT drop pg_trgm — it is owned by 0004 and shared (e.g. ix_runs_template_trgm).
