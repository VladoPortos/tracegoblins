"""two-factor auth: recovery codes + pending logins, widen totp_secret (M7)

Revision ID: 0009
Revises: 0008
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # totp_secret now holds Fernet ciphertext (~100+ chars), not a 32-char base32 secret.
    op.alter_column("users", "totp_secret", type_=sa.Text(), existing_nullable=True)
    op.add_column("users", sa.Column("totp_confirmed_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("users", sa.Column("totp_last_used_step", sa.BigInteger(), nullable=True))

    op.create_table(
        "mfa_recovery_codes",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("code_hash", sa.Text(), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_mfa_recovery_codes_user", "mfa_recovery_codes", ["user_id"])

    op.create_table(
        "pending_logins",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("remember", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("ip", sa.Text(), nullable=True),
        sa.Column("user_agent", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_pending_logins_user", "pending_logins", ["user_id"])


def downgrade() -> None:
    op.drop_table("pending_logins")
    op.drop_index("ix_mfa_recovery_codes_user", table_name="mfa_recovery_codes")
    op.drop_table("mfa_recovery_codes")
    op.drop_column("users", "totp_last_used_step")
    op.drop_column("users", "totp_confirmed_at")
    op.alter_column("users", "totp_secret", type_=sa.String(64), existing_nullable=True)
