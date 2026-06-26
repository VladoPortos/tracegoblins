from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel


class HostRecap(BaseModel):
    host: str
    ok: int = 0
    changed: int = 0
    unreachable: int = 0
    failed: int = 0
    skipped: int = 0


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
    counts: RunCounts
    recap: list[HostRecap]
    created_at: datetime
    team_id: str | None = None
    team_name: str | None = None
    controller_id: str | None = None
    controller_name: str | None = None
    awx_organization_name: str | None = None
    awx_launch_type: str | None = None
    elapsed: float | None = None
    scm_revision: str | None = None


class RunDetail(RunCard):
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
    duration_s: float | None = None  # job_events durations; None for stdout runs


class TaskFull(TaskLean):
    output: str | None
    error: str | None
    included_path: str | None


class DiffEntry(BaseModel):
    play_name: str
    task_name: str
    host: str
    before: str | None       # status in baseline; None = absent in baseline
    after: str | None        # status in current run; None = absent now
    seq: int                 # current-run seq (drawer-jump target) — always present on emitted entries


class DurationDelta(BaseModel):
    play_name: str
    task_name: str
    seq: int                 # current-run seq
    before_s: float
    after_s: float
    delta_s: float


class RunDiffOut(BaseModel):
    baseline: RunCard | None
    reason: Literal["no_template", "no_green_run"] | None  # set when baseline is None
    newly_failing: list[DiffEntry]
    fixed: list[DiffEntry]
    still_failing: list[DiffEntry]
    added_count: int
    removed_count: int
    hosts_newly_unreachable: list[str]
    duration_delta_s: float | None
    slowest_changes: list[DurationDelta]


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
