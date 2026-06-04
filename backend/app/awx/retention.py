from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models import Run
from app.services.audit import write_audit

_BATCH = 500


async def run_retention_sweep(db: AsyncSession | None = None) -> int:
    """Delete source='awx' runs older than RETENTION_DAYS, in batches, cascading
    tasks/run_raw/annotations/comments/shares via the existing FKs. source='upload'
    runs are NEVER deleted. Writes ONE audit row action='retention_sweep'. Returns the
    count. No-op (returns 0) when retention_days <= 0. Opens its own SessionLocal() when
    db is None (the scheduler cron path).

    A pruned-then-re-listed AWX job will NOT reappear on the next sync because the
    controller's last_synced_job_id only moves forward and the AWX id__gt cursor
    excludes everything at or below it.
    """
    days = settings.retention_days
    if days <= 0:
        return 0

    owns_session = db is None
    if owns_session:
        from app.db.session import SessionLocal

        db = SessionLocal()
    try:
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        total = 0
        while True:
            ids = (
                await db.scalars(
                    select(Run.id)
                    .where(Run.source == "awx", Run.created_at < cutoff)
                    .limit(_BATCH)
                )
            ).all()
            if not ids:
                break
            await db.execute(delete(Run).where(Run.id.in_(ids)))
            total += len(ids)
            await db.commit()

        await write_audit(
            db,
            action="retention_sweep",
            metadata={"deleted": total, "retention_days": days},
        )
        await db.commit()
        return total
    finally:
        if owns_session:
            await db.close()
