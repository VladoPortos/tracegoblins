import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger, DateTime, ForeignKey, Index, Integer, String, Text,
    UniqueConstraint, Uuid, func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    controller_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("awx_controllers.id", ondelete="CASCADE"), nullable=False
    )
    awx_project_id: Mapped[int] = mapped_column(Integer, nullable=False)
    name: Mapped[str] = mapped_column(Text)
    scm_type: Mapped[str] = mapped_column(String(16), default="")        # 'git' | '' | hg/svn...
    scm_url: Mapped[str | None] = mapped_column(Text, default=None)
    scm_branch: Mapped[str | None] = mapped_column(Text, default=None)
    scm_revision: Mapped[str | None] = mapped_column(Text, default=None)  # AWX current revision (info)
    description: Mapped[str | None] = mapped_column(Text, default=None)
    organization_id: Mapped[int | None] = mapped_column(Integer, default=None)
    organization_name: Mapped[str | None] = mapped_column(Text, default=None)
    # local clone status: unlinked -> pending -> cloning -> cloned | error
    status: Mapped[str] = mapped_column(String(16), server_default="unlinked", default="unlinked")
    git_url_override: Mapped[str | None] = mapped_column(Text, default=None)
    git_auth_type: Mapped[str | None] = mapped_column(String(8), default=None)  # none|token|userpass
    git_username: Mapped[str | None] = mapped_column(Text, default=None)
    git_secret_encrypted: Mapped[str | None] = mapped_column(Text, default=None)  # NEVER returned
    last_clone_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    last_clone_error: Mapped[str | None] = mapped_column(Text, default=None)
    clone_size_bytes: Mapped[int | None] = mapped_column(BigInteger, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        UniqueConstraint("controller_id", "awx_project_id",
                         name="uq_projects_controller_awx_project"),
        Index("ix_projects_organization_id", "organization_id"),
    )
