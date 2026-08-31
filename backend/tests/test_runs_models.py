import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.models import Run, RunRaw, Task, User


async def _owner(db):
    u = User(email="o@example.com", password_hash="x", display_name="O")
    db.add(u)
    await db.flush()
    return u


async def test_run_task_runraw_roundtrip(db):
    u = await _owner(db)
    run = Run(source="upload", owner_user_id=u.id, status="failed",
              host_count=1, task_count=1, warnings_count=0,
              recap=[{"host": "h1", "ok": 1, "changed": 0, "unreachable": 1,
                      "failed": 0, "skipped": 0, "rescued": 0, "ignored": 0}],
              awx_job_id="11140", template_name="Day2")
    db.add(run)
    await db.flush()
    db.add(Task(run_id=run.id, seq=1, play_name="P", name="t", status="unreachable",
                hosts={"h1": "unreachable"}, items_count=0, line_no=5))
    db.add(RunRaw(run_id=run.id, content="PLAY [..]"))
    await db.flush()

    got = await db.scalar(select(Run).where(Run.id == run.id))
    assert got.recap[0]["unreachable"] == 1 and got.awx_job_id == "11140"
    task = await db.scalar(select(Task).where(Task.run_id == run.id))
    assert task.hosts == {"h1": "unreachable"} and task.status == "unreachable"
    raw = await db.scalar(select(RunRaw).where(RunRaw.run_id == run.id))
    assert raw.content == "PLAY [..]"


async def test_duplicate_run_seq_rejected(db):
    u = await _owner(db)
    run = Run(source="upload", owner_user_id=u.id, status="ok",
              host_count=0, task_count=2, warnings_count=0, recap=[])
    db.add(run)
    await db.flush()
    db.add(Task(run_id=run.id, seq=1, play_name="P", name="a", status="ok", hosts={}, items_count=0))
    await db.flush()
    # a second (run_id, seq)=(.., 1) must violate uq_tasks_run_seq -> IntegrityError
    with pytest.raises(IntegrityError):
        async with db.begin_nested():
            db.add(Task(run_id=run.id, seq=1, play_name="P", name="b", status="ok", hosts={}, items_count=0))
            await db.flush()


async def test_delete_run_cascades(db):
    from sqlalchemy import func
    u = await _owner(db)
    run = Run(source="upload", owner_user_id=u.id, status="ok",
              host_count=0, task_count=1, warnings_count=0, recap=[])
    db.add(run)
    await db.flush()
    db.add(Task(run_id=run.id, seq=1, play_name="P", name="t", status="ok", hosts={}, items_count=0))
    db.add(RunRaw(run_id=run.id, content="x"))
    await db.flush()
    await db.delete(run)
    await db.flush()
    assert await db.scalar(select(func.count()).select_from(Task).where(Task.run_id == run.id)) == 0
    assert await db.scalar(select(func.count()).select_from(RunRaw).where(RunRaw.run_id == run.id)) == 0
