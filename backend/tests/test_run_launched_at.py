"""Run.launched_at: nullable column exists in the model + DB."""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select, text

from app.models import Run
from app.services.runs_query import run_to_card


async def test_launched_at_nullable_defaults_none(db):
    run = Run(source="awx", owner_user_id=None, status="successful",
              host_count=0, task_count=0, warnings_count=0, recap=[])
    db.add(run)
    await db.flush()
    got = await db.scalar(select(Run).where(Run.id == run.id))
    assert got.launched_at is None


async def test_launched_at_in_information_schema(db):
    row = await db.execute(text(
        "SELECT is_nullable, data_type FROM information_schema.columns "
        "WHERE table_name='runs' AND column_name='launched_at'"
    ))
    r = row.one()
    assert r.is_nullable == "YES"
    assert "timestamp" in r.data_type.lower()


async def test_run_to_card_exposes_launched_at(db, make_user):
    user = await make_user(email="launched_card@example.com")
    when = datetime(2026, 6, 4, 10, 0, 1, tzinfo=timezone.utc)
    run = Run(source="awx", owner_user_id=user.id, status="ok",
              host_count=0, task_count=0, warnings_count=0, recap=[],
              launched_at=when)
    db.add(run)
    await db.flush()
    card = run_to_card(run)
    assert card.launched_at == when
