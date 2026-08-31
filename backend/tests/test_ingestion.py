from __future__ import annotations

from datetime import timezone
from pathlib import Path

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select

from app.models import RunRaw, Task, User
from app.logparser import ParsedRun, ParsedTask, Play
from app.services.ingestion import _parse_log_time, build_run_from_parsed, ingest_upload

ROOT = Path(__file__).resolve().parents[2]  # repo root
UPLOADS = ROOT / "backend/tests/fixtures/logs"


async def _user(db):
    u = User(email="up@example.com", password_hash="x", display_name="Up")
    db.add(u)
    await db.flush()
    return u


async def test_ingest_job_11140(db):
    u = await _user(db)
    raw = (UPLOADS / "job_11140.txt").read_bytes()
    run = await ingest_upload(db, owner=u, raw_bytes=raw, ip="1.2.3.4")
    await db.flush()
    assert run.task_count == 178 and run.warnings_count == 2
    assert run.awx_job_id == "11140" and run.template_name == "Day2Actions - vstrycek"
    assert run.status == "unreachable"  # literal worst status (one unreachable task)
    assert run.host_count == 2
    n = await db.scalar(select(func.count()).select_from(Task).where(Task.run_id == run.id))
    assert n == 178
    seqs = (await db.execute(select(Task.seq).where(Task.run_id == run.id).order_by(Task.seq))).scalars().all()
    assert seqs == list(range(1, 179))  # 1-based, contiguous
    gather = await db.scalar(select(Task).where(Task.run_id == run.id, Task.name == "Gather Linux facts"))
    assert gather.status == "unreachable" and gather.hosts == {"pk-test-01": "unreachable"}
    raw_row = await db.scalar(select(RunRaw.content).where(RunRaw.run_id == run.id))
    assert raw_row == raw.decode("utf-8")


async def test_ingest_template_override_and_empty_meta(db):
    u = await _user(db)
    raw = (UPLOADS / "job_11181.txt").read_bytes()  # empty meta (no AWX Job Start block)
    run = await ingest_upload(db, owner=u, raw_bytes=raw, template_override="My Override")
    assert run.awx_job_id is None and run.template_name == "My Override"
    assert run.awx_user is None and run.log_time is None
    assert run.status == "changed"  # no failures


@pytest.mark.parametrize("awx_status", ["failed", "error", "canceled"])
def test_awx_terminal_failure_overrides_green_tasks(awx_status):
    """Removing the AWX failure floor would incorrectly store this run as changed."""
    parsed = ParsedRun(
        task_count=1,
        plays=[Play(name="play", tasks=[
            ParsedTask(name="task", statuses={"host": "ok"}),
        ])],
    )

    run, _ = build_run_from_parsed(
        parsed,
        source="awx",
        owner_user_id=None,
        team_id=None,
        template_name="job",
        awx_user=None,
        log_time=None,
        awx_job_status=awx_status,
    )

    assert run.status == "failed"


def test_successful_awx_job_preserves_task_derived_changed_status():
    """Applying the failure floor to successful jobs would mask a changed task rollup."""
    parsed = ParsedRun(
        task_count=1,
        plays=[Play(name="play", tasks=[
            ParsedTask(name="task", statuses={"host": "changed"}),
        ])],
    )

    run, _ = build_run_from_parsed(
        parsed,
        source="awx",
        owner_user_id=None,
        team_id=None,
        template_name="job",
        awx_user=None,
        log_time=None,
        awx_job_status="successful",
    )

    assert run.status == "changed"


def test_awx_terminal_failure_does_not_override_unreachable_task():
    """Lowering unreachable to failed would discard the task rollup's stronger signal."""
    parsed = ParsedRun(
        task_count=1,
        plays=[Play(name="play", tasks=[
            ParsedTask(name="task", statuses={"host": "unreachable"}),
        ])],
    )

    run, _ = build_run_from_parsed(
        parsed,
        source="awx",
        owner_user_id=None,
        team_id=None,
        template_name="job",
        awx_user=None,
        log_time=None,
        awx_job_status="failed",
    )

    assert run.status == "unreachable"


def test_parse_log_time():
    dt = _parse_log_time("2026-06-02 17:43:42 UTC")
    assert dt is not None and dt.tzinfo == timezone.utc and dt.hour == 17
    assert _parse_log_time(None) is None
    assert _parse_log_time("garbage") is None
    assert _parse_log_time("") is None


async def test_guards(db):
    u = await _user(db)
    with pytest.raises(HTTPException) as e:
        await ingest_upload(db, owner=u, raw_bytes=b"")
    assert e.value.status_code == 422
    with pytest.raises(HTTPException) as e:
        await ingest_upload(db, owner=u, raw_bytes=b"x" * (8 * 1024 * 1024 + 1))
    assert e.value.status_code == 413
    with pytest.raises(HTTPException) as e:
        await ingest_upload(db, owner=u, raw_bytes=b"\xff\xfe\x00\x01\x02\x03\x04")
    assert e.value.status_code == 415
    # whitespace-only decodes fine but is still junk -> 422 (covers paste + file paths)
    with pytest.raises(HTTPException) as e:
        await ingest_upload(db, owner=u, raw_bytes=b"   \n\t  ")
    assert e.value.status_code == 422
