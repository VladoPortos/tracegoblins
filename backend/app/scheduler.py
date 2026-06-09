# app/scheduler.py
from __future__ import annotations

import logging

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Advisory-lock constants
# ---------------------------------------------------------------------------

_LOCK_NAMESPACE = 0x41575835  # "AWX5" — per-controller namespace (from sync.py)
LEADER_KEY = 0x41575834      # "AWX4" — distinct from the per-controller namespace

# ---------------------------------------------------------------------------
# Module-level scheduler state
# ---------------------------------------------------------------------------

_scheduler: AsyncIOScheduler | None = None
_leader_conn: AsyncConnection | None = None
_is_leader: bool = False

# ---------------------------------------------------------------------------
# D5: leader-election helper
# ---------------------------------------------------------------------------


async def _try_leader_lock(conn: AsyncConnection) -> bool:
    """Non-blocking session-level advisory lock on LEADER_KEY for THIS connection.

    Returns True if this connection became the leader, False if another already holds it.
    The lock is SESSION-level: it survives commits/rollbacks and is held until the
    connection closes or an explicit pg_advisory_unlock is called.
    """
    return bool(
        await conn.scalar(text("SELECT pg_try_advisory_lock(:k)").bindparams(k=LEADER_KEY))
    )


# ---------------------------------------------------------------------------
# D6: job registration
# ---------------------------------------------------------------------------


async def _register_all(scheduler: AsyncIOScheduler, db: AsyncSession) -> None:
    """Register one interval job per auto-mode controller + a daily retention cron job.

    Per-controller advisory lock inside sync_controller prevents overlap with a manual sync.
    """
    from sqlalchemy import select

    from app.models import AwxController

    controllers = (
        await db.scalars(
            select(AwxController).where(AwxController.sync_mode == "auto")
        )
    ).all()

    for ctrl in controllers:
        scheduler.add_job(
            _run_sync,
            trigger=IntervalTrigger(minutes=ctrl.sync_interval_minutes),
            args=[str(ctrl.id)],
            id=f"sync:{ctrl.id}",
            replace_existing=True,
            max_instances=1,
            coalesce=True,
        )

    scheduler.add_job(
        _run_retention,
        trigger=CronTrigger(hour=3, minute=0),
        id="retention",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )


async def _run_sync(controller_id: str) -> None:
    """APScheduler target: fresh session, load the controller, run one sync.

    The per-controller advisory lock inside sync_controller prevents overlap with a
    manual sync triggered via the API.
    """
    from sqlalchemy import select

    from app.awx.sync import sync_controller
    from app.db.session import SessionLocal
    from app.models import AwxController

    async with SessionLocal() as db:
        ctrl = await db.scalar(select(AwxController).where(AwxController.id == controller_id))
        if ctrl is None:
            return
        await sync_controller(db, ctrl)


async def _run_retention() -> None:
    """APScheduler cron target: run the daily retention sweep."""
    from app.awx.retention import run_retention_sweep

    await run_retention_sweep()


# ---------------------------------------------------------------------------
# D7: reconcile_controller — hot-reload one controller's auto-sync job
# ---------------------------------------------------------------------------


def reconcile_controller(
    controller_id: str,
    *,
    sync_mode: str,
    sync_interval_minutes: int | None,
    deleted: bool = False,
) -> None:
    """Hot-reload one controller's auto-sync job. Idempotent.

    Not leader / no scheduler -> no-op. deleted OR sync_mode != 'auto' -> remove
    'sync:{id}' if present. sync_mode == 'auto' -> add/reschedule (replace_existing).
    """
    if not _is_leader or _scheduler is None:
        return
    job_id = f"sync:{controller_id}"
    if deleted or sync_mode != "auto" or not sync_interval_minutes or sync_interval_minutes <= 0:
        if _scheduler.get_job(job_id) is not None:
            _scheduler.remove_job(job_id)
        return
    _scheduler.add_job(
        _run_sync,
        trigger=IntervalTrigger(minutes=sync_interval_minutes),
        args=[controller_id],
        id=job_id,
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )


# ---------------------------------------------------------------------------
# D8: start_scheduler / stop_scheduler
# ---------------------------------------------------------------------------


async def start_scheduler() -> None:
    """Lifespan entry. Try to become leader; if so, build + register + start the scheduler.

    Disabled (scheduler_enabled=False) or non-leader workers no-op. Uses one dedicated
    long-lived connection from the app engine to hold the session-level leader lock for
    the whole process lifetime.
    """
    global _scheduler, _leader_conn, _is_leader

    from app.core.config import settings

    if not settings.scheduler_enabled:
        return

    from app.db.session import SessionLocal, engine

    conn = await engine.connect()
    if not await _try_leader_lock(conn):
        await conn.close()
        return

    # We are the leader. Build + register + start ATOMICALLY: assign the module-global _scheduler
    # only after a successful start, and if anything below fails, release the leader lock and reset
    # state. Otherwise a transient failure (e.g. a DB hiccup during _register_all) would leave
    # LEADER_KEY pinned on _leader_conn forever — no other worker could take over — with a
    # half-built, never-started scheduler stranded in _scheduler.
    _leader_conn = conn
    _is_leader = True
    try:
        scheduler = AsyncIOScheduler()
        async with SessionLocal() as db:
            await _register_all(scheduler, db)
        scheduler.start()
        _scheduler = scheduler
    except Exception:
        _scheduler = None
        await stop_scheduler()  # releases the leader lock, closes _leader_conn, resets _is_leader
        raise


async def stop_scheduler() -> None:
    """Shut the scheduler (if leader), release the leader lock, and close the connection.

    Crash-safe + idempotent: a failure shutting the scheduler down (it was never fully started, or
    its event loop is already gone) must NOT skip releasing the leader advisory lock and closing the
    connection — otherwise LEADER_KEY stays held and no worker can take over. Closing _leader_conn
    is itself a backstop: Postgres drops session-level advisory locks when the backend disconnects.
    """
    global _scheduler, _leader_conn, _is_leader

    if _scheduler is not None:
        try:
            _scheduler.shutdown(wait=False)
        except Exception:
            logger.exception("scheduler shutdown failed; releasing leader lock anyway")
        _scheduler = None
    if _leader_conn is not None:
        try:
            await _leader_conn.execute(
                text("SELECT pg_advisory_unlock(:k)").bindparams(k=LEADER_KEY)
            )
            await _leader_conn.commit()
        except Exception:
            logger.exception("failed to release leader advisory lock cleanly")
        finally:
            try:
                await _leader_conn.close()  # drops the session-level lock even if unlock failed
            except Exception:
                logger.exception("failed to close leader connection")
        _leader_conn = None
    _is_leader = False
