from __future__ import annotations

import uuid
from dataclasses import asdict
from datetime import datetime, timezone

from fastapi import HTTPException, status
from fastapi.concurrency import run_in_threadpool
from sqlalchemy.ext.asyncio import AsyncSession

from app.logparser import ParsedRun, parse_stdout
from app.models import Run, RunRaw, Task, User
from app.services.audit import write_audit

MAX_UPLOAD_BYTES = 8 * 1024 * 1024  # 8 MB


def _parse_log_time(raw: str | None) -> datetime | None:
    """'YYYY-MM-DD HH:MM:SS UTC' -> aware UTC datetime; None on absence/failure."""
    if not raw:
        return None
    s = raw.strip()
    if s.endswith("UTC"):
        s = s[:-3].strip()
    try:
        return datetime.strptime(s, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _guard_and_decode(data: bytes) -> str:
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, detail="Log exceeds 8 MB")
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, detail="Log is not UTF-8 text")
    if not text.strip():  # reject empty AND whitespace-only paste/upload (covers both paths)
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail="Empty log")
    sample = text[:65536]
    if sample:
        printable = sum(1 for c in sample if c in "\n\t\r" or c >= " ")
        if printable / len(sample) < 0.85:
            raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, detail="Log appears binary")
    return text


def build_run_from_parsed(
    parsed: ParsedRun,
    *,
    source: str,
    owner_user_id: uuid.UUID | None,
    team_id: uuid.UUID | None,
    template_name: str | None,
    awx_user: str | None,
    log_time: datetime | None,
    awx_job_status: str | None = None,
    controller_id: uuid.UUID | None = None,
    awx_job_id: str | None = None,
    awx_job_url: str | None = None,
    awx_organization_id: int | None = None,
    awx_organization_name: str | None = None,
    awx_launch_type: str | None = None,
    awx_workflow_name: str | None = None,
) -> tuple[Run, list[Task]]:
    """The M2 mapping: seq 1..N over plays/tasks, status=pt.dominant(), literal-worst
    run status (unreachable>failed>changed>ok, else ok), recap=[asdict(r)...]. Returns
    an unflushed Run + its Tasks (caller sets run_id after flush)."""
    tasks: list[Task] = []
    seq = 0
    for play in parsed.plays:
        for pt in play.tasks:
            seq += 1
            tasks.append(Task(
                seq=seq,
                play_name=play.name,
                role=pt.role,
                name=pt.name,
                status=pt.dominant(),
                hosts=dict(pt.statuses),
                items_count=pt.items,
                output=pt.output or None,
                error=pt.error,
                line_no=pt.line,
                included_path=pt.included_path,
                duration_s=pt.duration_s,  # job_events only; None for stdout
            ))

    task_statuses = {t.status for t in tasks}
    # Literal worst: first match in priority order; not collapsed (unreachable stays unreachable).
    # included/skipped-only and zero-task runs intentionally resolve to 'ok' per the M2 contract.
    run_status = next(
        (s for s in ("unreachable", "failed", "changed", "ok") if s in task_statuses), "ok"
    )
    if awx_job_status in {"failed", "error", "canceled"} and run_status in {"ok", "changed"}:
        run_status = "failed"

    run = Run(
        source=source,
        owner_user_id=owner_user_id,
        team_id=team_id,
        controller_id=controller_id,
        awx_job_id=awx_job_id,
        awx_job_url=awx_job_url,
        template_name=template_name,
        awx_user=awx_user,
        log_time=log_time,
        status=run_status,
        host_count=len(parsed.recap),
        task_count=parsed.task_count,
        warnings_count=parsed.warnings,
        recap=[asdict(r) for r in parsed.recap],
        awx_organization_id=awx_organization_id,
        awx_organization_name=awx_organization_name,
        awx_launch_type=awx_launch_type,
        awx_workflow_name=awx_workflow_name,
    )
    return run, tasks


async def ingest_upload(
    db: AsyncSession, *, owner: User, raw_bytes: bytes,
    template_override: str | None = None, team_id: uuid.UUID | None = None,
    ip: str | None = None,
) -> Run:
    text = _guard_and_decode(raw_bytes)
    parsed = await run_in_threadpool(parse_stdout, text)  # CPU-bound off the event loop

    run, tasks = build_run_from_parsed(
        parsed,
        source="upload",
        owner_user_id=owner.id,
        team_id=team_id,
        template_name=template_override or parsed.meta.template,
        awx_user=parsed.meta.user,
        log_time=_parse_log_time(parsed.meta.log_time),
        awx_job_id=parsed.meta.job_id,
    )

    db.add(run)
    await db.flush()  # assign run.id before referencing it

    for t in tasks:
        t.run_id = run.id
    db.add_all(tasks)
    db.add(RunRaw(run_id=run.id, content=text))

    await write_audit(
        db,
        action="run_upload",
        actor_id=owner.id,
        target_type="run",
        target_id=str(run.id),
        ip=ip,
        metadata={"job_id": parsed.meta.job_id, "task_count": parsed.task_count},
    )
    return run  # caller (route) owns the commit
