import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean, DateTime, ForeignKey, Index, Integer, String, Text, Uuid, func, text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class AwxController(Base):
    __tablename__ = "awx_controllers"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(Text, unique=True)
    base_url: Mapped[str] = mapped_column(Text)
    auth_token_encrypted: Mapped[str] = mapped_column(Text)
    verify_ssl: Mapped[bool] = mapped_column(Boolean, server_default=text("true"), default=True)
    sync_mode: Mapped[str] = mapped_column(String(8), server_default="manual", default="manual")
    sync_interval_minutes: Mapped[int | None] = mapped_column(Integer, default=None)
    last_synced_job_id: Mapped[int | None] = mapped_column(Integer, default=None)
    last_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    last_sync_status: Mapped[str] = mapped_column(String(8), server_default="never", default="never")
    last_sync_error: Mapped[str | None] = mapped_column(Text, default=None)
    # M6: live progress for the running sync (all NULL between syncs)
    sync_total: Mapped[int | None] = mapped_column(Integer, default=None)
    sync_done: Mapped[int | None] = mapped_column(Integer, default=None)
    sync_current_job: Mapped[str | None] = mapped_column(Text, default=None)
    status: Mapped[str] = mapped_column(String(12), server_default="unconfigured", default="unconfigured")
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), default=None
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class ControllerTeam(Base):
    __tablename__ = "controller_teams"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    controller_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("awx_controllers.id", ondelete="CASCADE")
    )
    team_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("teams.id", ondelete="CASCADE"))
    awx_organization_id: Mapped[int | None] = mapped_column(Integer, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index("ix_controller_teams_team", "team_id"),
        Index("ix_controller_teams_controller", "controller_id"),
        Index("uq_controller_teams_specific", "controller_id", "team_id", "awx_organization_id",
              unique=True, postgresql_where=text("awx_organization_id IS NOT NULL")),
        Index("uq_controller_teams_allorgs", "controller_id", "team_id",
              unique=True, postgresql_where=text("awx_organization_id IS NULL")),
    )
