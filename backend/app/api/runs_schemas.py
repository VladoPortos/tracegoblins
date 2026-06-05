from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class HostRecap(BaseModel):
    host: str
    ok: int = 0
    changed: int = 0
    unreachable: int = 0
    failed: int = 0
    skipped: int = 0
    rescued: int = 0
    ignored: int = 0


class RunCounts(BaseModel):
    ok: int = 0
    changed: int = 0
    unreachable: int = 0
    failed: int = 0
    skipped: int = 0


class RunCard(BaseModel):
    id: str
    job_id: str | None
    template_name: str | None
    status: str
    log_time: datetime | None
    launched_at: datetime | None = None
    host_count: int
    task_count: int
    warnings_count: int
    counts: RunCounts
    recap: list[HostRecap]
    created_at: datetime
    team_id: str | None = None
    team_name: str | None = None
    controller_id: str | None = None
    controller_name: str | None = None
    awx_organization_id: int | None = None
    awx_organization_name: str | None = None
    awx_launch_type: str | None = None
    awx_workflow_name: str | None = None
    elapsed: float | None = None


class RunDetail(RunCard):
    source: str
    owner_user_id: str | None


class RunCreated(BaseModel):
    id: str


class RunList(BaseModel):
    items: list[RunCard]
    total: int


class TaskLean(BaseModel):
    seq: int
    play_name: str
    role: str | None
    name: str
    status: str
    hosts: dict[str, str]
    items_count: int
    line_no: int | None
    has_output: bool
    has_error: bool
    duration_s: float | None = None  # job_events durations; None for stdout runs


class TaskFull(TaskLean):
    output: str | None
    error: str | None
    included_path: str | None


class FacetOrg(BaseModel):
    id: int
    name: str | None


class FacetController(BaseModel):
    id: str
    name: str | None


class FacetsOut(BaseModel):
    organizations: list[FacetOrg]
    templates: list[str]
    controllers: list[FacetController]
    statuses: list[str]
    launch_types: list[str]
    users: list[str]
