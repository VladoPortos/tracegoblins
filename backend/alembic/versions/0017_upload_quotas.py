"""add uploaded-run byte accounting

Revision ID: 0017
Revises: 0016
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0017"
down_revision = "0016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("runs", sa.Column(
        "upload_size_bytes", sa.BigInteger(), nullable=False, server_default="0"
    ))
    # Include pre-migration uploads in the byte quota. PostgreSQL stores text as UTF-8 in the
    # supported deployment, so octet_length matches the byte count recorded for new uploads.
    op.execute(sa.text("""
        UPDATE runs
        SET upload_size_bytes = octet_length(run_raw.content)
        FROM run_raw
        WHERE run_raw.run_id = runs.id AND runs.source = 'upload'
    """))
    op.alter_column("runs", "upload_size_bytes", server_default=None)


def downgrade() -> None:
    op.drop_column("runs", "upload_size_bytes")
