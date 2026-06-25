import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    DateTime, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint, Uuid, func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class Run(Base):
    __tablename__ = "runs"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    source: Mapped[str] = mapped_column(String(16), default="upload")  # 'upload' | 'awx'
    owner_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True
    )
    team_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("teams.id", ondelete="SET NULL"), default=None
    )
    controller_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("awx_controllers.id", ondelete="CASCADE"), default=None
    )
    awx_job_id: Mapped[str | None] = mapped_column(String(64), default=None)  # parsed job number in M2
    awx_job_url: Mapped[str | None] = mapped_column(Text, default=None)
    awx_user: Mapped[str | None] = mapped_column(String(255), default=None)
    awx_organization_id: Mapped[int | None] = mapped_column(Integer, default=None)
    awx_organization_name: Mapped[str | None] = mapped_column(Text, default=None)
    awx_launch_type: Mapped[str | None] = mapped_column(String(16), default=None)
    awx_workflow_name: Mapped[str | None] = mapped_column(Text, default=None)
    template_name: Mapped[str | None] = mapped_column(Text, default=None)
    log_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    launched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    status: Mapped[str] = mapped_column(String(16))
    host_count: Mapped[int] = mapped_column(Integer, default=0)
    task_count: Mapped[int] = mapped_column(Integer, default=0)
    warnings_count: Mapped[int] = mapped_column(Integer, default=0)
    elapsed: Mapped[float | None] = mapped_column(Float, default=None)
    recap: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    # Path Explorer inputs (M1) — captured from GET /jobs/{id}/. project_id/scm_revision
    # are unused in M1 but captured now so M2 auto-link + M3 source-fetch are free.
    project_id: Mapped[int | None] = mapped_column(Integer, default=None)
    project_name: Mapped[str | None] = mapped_column(Text, default=None)
    job_template_id: Mapped[int | None] = mapped_column(Integer, default=None)
    scm_revision: Mapped[str | None] = mapped_column(Text, default=None)
    awx_limit: Mapped[str | None] = mapped_column(Text, default=None)  # 'limit' is reserved
    extra_vars: Mapped[dict[str, Any] | None] = mapped_column(JSONB, default=None)
    survey: Mapped[dict[str, Any] | None] = mapped_column(JSONB, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    tasks: Mapped[list["Task"]] = relationship(
        back_populates="run", cascade="all, delete-orphan", passive_deletes=True
    )
    raw: Mapped["RunRaw"] = relationship(
        back_populates="run", cascade="all, delete-orphan", passive_deletes=True, uselist=False
    )

    __table_args__ = (
        UniqueConstraint("controller_id", "awx_job_id", name="uq_runs_controller_id_awx_job_id"),
        Index("ix_runs_owner_created", "owner_user_id", created_at.desc()),
        Index("ix_runs_team_created", "team_id", created_at.desc()),
        Index("ix_runs_controller_created", "controller_id", created_at.desc()),
        Index("ix_runs_org", "awx_organization_id"),
        Index("ix_runs_status", "status"),
        Index("ix_runs_awx_user", "awx_user"),
        Index("ix_runs_template_trgm", "template_name",
              postgresql_using="gin", postgresql_ops={"template_name": "gin_trgm_ops"}),
        # Effective-timestamp expression index matching app.services.run_time.run_when_expr,
        # used by the analytics window scan and the run-diff baseline lookup. Makes the
        # coalesce(...) range/sort sargable instead of a per-row recompute.
        Index("ix_runs_when", func.coalesce(launched_at, log_time, created_at)),
    )


class Task(Base):
    __tablename__ = "tasks"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"), nullable=False)
    seq: Mapped[int] = mapped_column(Integer)
    play_name: Mapped[str] = mapped_column(Text)
    role: Mapped[str | None] = mapped_column(Text, default=None)
    name: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16))
    hosts: Mapped[dict[str, str]] = mapped_column(JSONB, default=dict)
    items_count: Mapped[int] = mapped_column(Integer, default=0)
    output: Mapped[str | None] = mapped_column(Text, default=None)
    error: Mapped[str | None] = mapped_column(Text, default=None)
    line_no: Mapped[int | None] = mapped_column(Integer, default=None)
    included_path: Mapped[str | None] = mapped_column(Text, default=None)
    # Per-task wall-clock seconds from the AWX job_events `created` deltas. NULL for
    # stdout-parsed runs (AWX default stdout has no per-task timestamps).
    duration_s: Mapped[float | None] = mapped_column(Float, default=None)

    run: Mapped["Run"] = relationship(back_populates="tasks")

    __table_args__ = (
        # Unique (run_id, seq): also serves the get_task lookup + ORDER BY seq within a run,
        # so accidental duplicate writes raise IntegrityError instead of get_task returning
        # an arbitrary row. No separate non-unique index needed.
        UniqueConstraint("run_id", "seq", name="uq_tasks_run_seq"),
        Index("ix_tasks_run_status", "run_id", "status"),
    )


class RunRaw(Base):
    __tablename__ = "run_raw"

    run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"), primary_key=True)
    content: Mapped[str] = mapped_column(Text)

    run: Mapped["Run"] = relationship(back_populates="raw")


class RunNode(Base):
    __tablename__ = "run_nodes"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"), nullable=False)
    node_id: Mapped[str] = mapped_column(Text)                 # AWX-derived stable id
    parent_node_id: Mapped[str | None] = mapped_column(Text, default=None)
    counter: Mapped[int] = mapped_column(Integer, default=0)
    depth: Mapped[int] = mapped_column(Integer, default=0)
    node_type: Mapped[str] = mapped_column(String(16))
    name: Mapped[str] = mapped_column(Text)
    action: Mapped[str | None] = mapped_column(Text, default=None)
    task_path: Mapped[str | None] = mapped_column(Text, default=None)
    ansible_uuid: Mapped[str | None] = mapped_column(Text, default=None)
    is_conditional: Mapped[bool] = mapped_column(default=False)
    when_expr: Mapped[str | None] = mapped_column(Text, default=None)
    loop_var: Mapped[str | None] = mapped_column(Text, default=None)
    status: Mapped[str] = mapped_column(String(16), default="ok")
    changed: Mapped[bool] = mapped_column(default=False)
    host_count: Mapped[int] = mapped_column(Integer, default=0)
    item_count: Mapped[int] = mapped_column(Integer, default=0)
    child_count: Mapped[int] = mapped_column(Integer, default=0)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    duration_s: Mapped[float | None] = mapped_column(Float, default=None)
    args: Mapped[dict[str, Any] | None] = mapped_column(JSONB, default=None)

    __table_args__ = (
        UniqueConstraint("run_id", "node_id", name="uq_run_nodes_run_node"),
        Index("ix_run_nodes_run_parent", "run_id", "parent_node_id"),
    )


class RunNodeResult(Base):
    __tablename__ = "run_node_results"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"), nullable=False)
    node_id: Mapped[str] = mapped_column(Text)                 # denormalized RunNode.node_id
    host: Mapped[str] = mapped_column(Text)
    item_index: Mapped[int | None] = mapped_column(Integer, default=None)
    item_value: Mapped[Any | None] = mapped_column(JSONB, default=None)
    status: Mapped[str] = mapped_column(String(16), default="ok")
    changed: Mapped[bool] = mapped_column(default=False)
    result: Mapped[dict[str, Any] | None] = mapped_column(JSONB, default=None)
    skip_reason: Mapped[str | None] = mapped_column(Text, default=None)
    false_condition: Mapped[str | None] = mapped_column(Text, default=None)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    duration_s: Mapped[float | None] = mapped_column(Float, default=None)

    __table_args__ = (
        Index("ix_run_node_results_run_node", "run_id", "node_id"),
    )
