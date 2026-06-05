from __future__ import annotations

from sqlalchemy import Row

from app.api.runs_schemas import HostRecap, RunCard, RunCounts, RunDetail, TaskFull, TaskLean
from app.models import Run, Task

_COUNT_KEYS = ("ok", "changed", "unreachable", "failed", "skipped")


def _counts_from_recap(recap: list[dict]) -> RunCounts:
    agg = {k: 0 for k in _COUNT_KEYS}
    for row in recap or []:
        for k in _COUNT_KEYS:
            agg[k] += int(row.get(k, 0) or 0)
    return RunCounts(**agg)


def run_to_card(run: Run, team_name: str | None = None, controller_name: str | None = None) -> RunCard:
    return RunCard(
        id=str(run.id), job_id=run.awx_job_id, template_name=run.template_name,
        status=run.status, log_time=run.log_time, launched_at=run.launched_at,
        host_count=run.host_count,
        task_count=run.task_count, warnings_count=run.warnings_count,
        counts=_counts_from_recap(run.recap),
        recap=[HostRecap(**r) for r in (run.recap or [])],
        created_at=run.created_at,
        team_id=str(run.team_id) if run.team_id else None,
        team_name=team_name,
        controller_id=str(run.controller_id) if run.controller_id else None,
        controller_name=controller_name,
        awx_organization_id=run.awx_organization_id,
        awx_organization_name=run.awx_organization_name,
        awx_launch_type=run.awx_launch_type,
        awx_workflow_name=run.awx_workflow_name,
        elapsed=run.elapsed,
    )


def run_to_detail(run: Run, *, controller_name: str | None = None) -> RunDetail:
    return RunDetail(
        **run_to_card(run, controller_name=controller_name).model_dump(),
        source=run.source,
        owner_user_id=str(run.owner_user_id) if run.owner_user_id else None,
    )


def task_to_lean(t: Task) -> TaskLean:
    return TaskLean(
        seq=t.seq, play_name=t.play_name, role=t.role, name=t.name, status=t.status,
        hosts=t.hosts or {}, items_count=t.items_count, line_no=t.line_no,
        has_output=bool(t.output), has_error=t.error is not None,
        duration_s=t.duration_s,
    )


def row_to_lean(r: Row) -> TaskLean:
    """Map a lean SELECT row (lean columns + DB-computed has_output/has_error) to TaskLean."""
    return TaskLean(
        seq=r.seq, play_name=r.play_name, role=r.role, name=r.name, status=r.status,
        hosts=r.hosts or {}, items_count=r.items_count, line_no=r.line_no,
        has_output=r.has_output, has_error=r.has_error,
        duration_s=r.duration_s,
    )


def task_to_full(t: Task) -> TaskFull:
    return TaskFull(
        **task_to_lean(t).model_dump(),
        output=t.output, error=t.error, included_path=t.included_path,
    )
