from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select

from app.awx.retention import run_retention_sweep
from app.models import Run, RunRaw, Task


async def _mk_run(db, owner, *, source, age_days, status="successful"):
    """Insert a Run with created_at back-dated by age_days and one Task + RunRaw."""
    run = Run(
        source=source,
        owner_user_id=owner.id if source == "upload" else None,
        team_id=None,
        status=status,
        host_count=1,
        task_count=1,
        warnings_count=0,
        recap=[],
    )
    db.add(run)
    await db.flush()
    # Back-date created_at explicitly (server_default=now() would otherwise win).
    run.created_at = datetime.now(timezone.utc) - timedelta(days=age_days)
    db.add(Task(run_id=run.id, seq=1, play_name="p", name="t", status="ok", hosts={}))
    db.add(RunRaw(run_id=run.id, content="log"))
    await db.flush()
    return run


async def test_sweep_deletes_old_awx_keeps_upload_and_recent(db, make_user, monkeypatch):
    from app.core import config as cfg

    monkeypatch.setattr(cfg.settings, "retention_days", 90, raising=True)
    owner = await make_user(email="ret-owner@example.com")
    old_awx = await _mk_run(db, owner, source="awx", age_days=120, status="failed")
    recent_awx = await _mk_run(db, owner, source="awx", age_days=10)
    old_upload = await _mk_run(db, owner, source="upload", age_days=200)
    await db.commit()

    deleted = await run_retention_sweep(db)
    assert deleted == 1

    remaining = (await db.scalars(select(Run.id))).all()
    assert old_awx.id not in remaining
    assert recent_awx.id in remaining
    assert old_upload.id in remaining

    # Cascade: the old AWX run's task + raw are gone.
    assert await db.scalar(select(func.count()).select_from(Task).where(Task.run_id == old_awx.id)) == 0
    assert await db.scalar(select(func.count()).select_from(RunRaw).where(RunRaw.run_id == old_awx.id)) == 0


async def test_sweep_writes_audit_row(db, make_user, monkeypatch):
    from app.core import config as cfg
    from app.models import AuditLog

    monkeypatch.setattr(cfg.settings, "retention_days", 30, raising=True)
    owner = await make_user(email="ret-audit@example.com")
    await _mk_run(db, owner, source="awx", age_days=60)
    await _mk_run(db, owner, source="awx", age_days=61)
    await db.commit()

    n = await run_retention_sweep(db)
    assert n == 2

    rows = (
        await db.scalars(select(AuditLog).where(AuditLog.action == "retention_sweep"))
    ).all()
    assert len(rows) == 1
    assert rows[0].meta_ == {"deleted": 2, "retention_days": 30}


async def test_sweep_disabled_when_retention_zero(db, make_user, monkeypatch):
    from app.core import config as cfg
    from app.models import AuditLog
    from sqlalchemy import func, select

    monkeypatch.setattr(cfg.settings, "retention_days", 0, raising=True)
    owner = await make_user(email="ret-zero@example.com")
    old_awx = await _mk_run(db, owner, source="awx", age_days=999)
    await db.commit()

    n = await run_retention_sweep(db)
    assert n == 0

    # The ancient AWX run survives and no audit row is written.
    assert old_awx.id in (await db.scalars(select(Run.id))).all()
    assert await db.scalar(
        select(func.count()).select_from(AuditLog).where(AuditLog.action == "retention_sweep")
    ) == 0
