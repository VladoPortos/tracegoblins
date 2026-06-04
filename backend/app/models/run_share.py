import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint, DateTime, ForeignKey, Index, String, Uuid, func, text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class RunShare(Base):
    __tablename__ = "run_shares"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("runs.id", ondelete="CASCADE"), nullable=False
    )
    shared_with_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), default=None
    )
    shared_with_team_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("teams.id", ondelete="CASCADE"), default=None
    )
    permission: Mapped[str] = mapped_column(String(16), default="collaborate")  # future-tier seam
    shared_by_user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        CheckConstraint(
            "(shared_with_user_id IS NOT NULL) <> (shared_with_team_id IS NOT NULL)",
            name="exactly_one_target",
        ),
        Index(
            "uq_run_shares_user", "run_id", "shared_with_user_id",
            unique=True, postgresql_where=text("shared_with_user_id IS NOT NULL"),
        ),
        Index(
            "uq_run_shares_team", "run_id", "shared_with_team_id",
            unique=True, postgresql_where=text("shared_with_team_id IS NOT NULL"),
        ),
        Index("ix_run_shares_user", "shared_with_user_id"),
        Index("ix_run_shares_team", "shared_with_team_id"),
    )
