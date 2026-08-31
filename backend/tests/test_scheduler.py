from __future__ import annotations

import pytest
from cryptography.fernet import Fernet
from pydantic import SecretStr
from sqlalchemy import text


# ---------------------------------------------------------------------------
# Module-level: install a real Fernet key so encrypt_token works in these tests
# (the awx/ conftest autouse fixture only covers tests/awx/; scheduler tests
#  live here and also encrypt AWX tokens when setting up AwxController rows).
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _enc_key(monkeypatch):
    from app.core.config import settings as _s

    key = Fernet.generate_key().decode()
    monkeypatch.setattr(_s, "token_enc_key", SecretStr(key))


# ---------------------------------------------------------------------------
# Task D5 — leader election helpers
# ---------------------------------------------------------------------------


def test_leader_key_constant():
    from app.scheduler import LEADER_KEY, _LOCK_NAMESPACE as _NS

    assert LEADER_KEY == 0x41575834
    assert LEADER_KEY != _NS  # distinct from per-controller namespace


@pytest.mark.db_per_test
async def test_leader_lock_one_holder_blocks_second(engine):
    """Session-level advisory lock: first acquirer holds it; second gets False;
    releasing on A allows B to acquire."""
    from app.scheduler import LEADER_KEY, _try_leader_lock

    async with engine.connect() as conn_a, engine.connect() as conn_b:
        assert await _try_leader_lock(conn_a) is True   # first → True
        assert await _try_leader_lock(conn_b) is False  # second → blocked

        # release A; now B can acquire
        await conn_a.execute(text("SELECT pg_advisory_unlock(:k)").bindparams(k=LEADER_KEY))
        assert await _try_leader_lock(conn_b) is True

        # clean up
        await conn_b.execute(text("SELECT pg_advisory_unlock(:k)").bindparams(k=LEADER_KEY))


# ---------------------------------------------------------------------------
# Task D6 — _register_all
# ---------------------------------------------------------------------------


async def test_register_all_adds_sync_jobs_and_retention(db, make_user):
    from apscheduler.schedulers.asyncio import AsyncIOScheduler
    from apscheduler.triggers.cron import CronTrigger
    from apscheduler.triggers.interval import IntervalTrigger

    from app.core.crypto import encrypt_token
    from app.models import AwxController
    from app.scheduler import _register_all

    admin = await make_user(email="reg-admin@example.com", role="admin")

    # auto controller — should get a sync job
    db.add(AwxController(
        name="auto-ctrl-1", base_url="https://awx1.example",
        auth_token_encrypted=encrypt_token("tok1"),
        verify_ssl=False, sync_mode="auto", sync_interval_minutes=15,
        created_by_user_id=admin.id,
    ))
    # manual controller — must NOT get a sync job
    db.add(AwxController(
        name="manual-ctrl-1", base_url="https://awx2.example",
        auth_token_encrypted=encrypt_token("tok2"),
        verify_ssl=False, sync_mode="manual", sync_interval_minutes=None,
        created_by_user_id=admin.id,
    ))
    await db.commit()

    sched = AsyncIOScheduler()
    await _register_all(sched, db)

    job_ids = {j.id for j in sched.get_jobs()}

    # retention cron job must always be registered
    assert "retention" in job_ids
    retention_job = sched.get_job("retention")
    assert isinstance(retention_job.trigger, CronTrigger)

    # exactly one sync job (for the auto controller)
    sync_jobs = [j for j in sched.get_jobs() if j.id.startswith("sync:")]
    assert len(sync_jobs) == 1
    assert isinstance(sync_jobs[0].trigger, IntervalTrigger)
    assert sync_jobs[0].trigger.interval.total_seconds() == 15 * 60


# ---------------------------------------------------------------------------
# Task D7 — reconcile_controller
# ---------------------------------------------------------------------------


import uuid as _uuid


async def test_reconcile_controller_add_reschedule_remove():
    from apscheduler.schedulers.asyncio import AsyncIOScheduler

    import app.scheduler as sch

    cid = str(_uuid.uuid4())
    # The scheduler must be STARTED for replace_existing=True to take effect
    # in APScheduler 3.x (unstarted MemoryJobStore ignores replace semantics).
    # In production reconcile_controller is only ever called after start_scheduler()
    # has returned True (scheduler already started), so starting here is correct.
    scheduler = AsyncIOScheduler()
    scheduler.start()
    sch._scheduler = scheduler
    sch._is_leader = True
    try:
        # add
        sch.reconcile_controller(cid, sync_mode="auto", sync_interval_minutes=10)
        job = scheduler.get_job(f"sync:{cid}")
        assert job is not None
        assert job.trigger.interval.total_seconds() == 10 * 60

        # reschedule (replace_existing)
        sch.reconcile_controller(cid, sync_mode="auto", sync_interval_minutes=30)
        assert scheduler.get_job(f"sync:{cid}").trigger.interval.total_seconds() == 30 * 60

        # switch to manual -> removed
        sch.reconcile_controller(cid, sync_mode="manual", sync_interval_minutes=None)
        assert scheduler.get_job(f"sync:{cid}") is None

        # re-add then delete -> removed (idempotent remove on a missing job is safe)
        sch.reconcile_controller(cid, sync_mode="auto", sync_interval_minutes=5)
        assert scheduler.get_job(f"sync:{cid}") is not None
        sch.reconcile_controller(cid, sync_mode="auto", sync_interval_minutes=5, deleted=True)
        assert scheduler.get_job(f"sync:{cid}") is None
        # deleted + manual is also a no-op remove (safe when already absent)
        sch.reconcile_controller(cid, sync_mode="manual", sync_interval_minutes=None, deleted=True)
    finally:
        scheduler.shutdown(wait=False)
        sch._scheduler = None
        sch._is_leader = False


def test_reconcile_is_noop_when_not_leader():
    import app.scheduler as sch

    sch._scheduler = None
    sch._is_leader = False
    # Must not raise even though there is no scheduler.
    sch.reconcile_controller(str(_uuid.uuid4()), sync_mode="auto", sync_interval_minutes=10)


# ---------------------------------------------------------------------------
# Task D8 — start_scheduler / stop_scheduler
# ---------------------------------------------------------------------------


async def test_start_scheduler_noop_when_disabled(monkeypatch):
    import app.scheduler as sch
    from app.core import config as cfg

    monkeypatch.setattr(cfg.settings, "scheduler_enabled", False, raising=True)
    sch._scheduler = None
    sch._is_leader = False
    await sch.start_scheduler()
    assert sch._scheduler is None
    assert sch._is_leader is False
    # stop must be safe even though start was a no-op.
    await sch.stop_scheduler()


@pytest.mark.db_per_test
async def test_start_scheduler_becomes_leader_and_registers(db, make_user, monkeypatch):
    import app.scheduler as sch
    from app.core import config as cfg
    from app.core.crypto import encrypt_token
    from app.models import AwxController

    admin = await make_user(email="leader-admin@example.com", role="admin")
    db.add(AwxController(
        name="leader-auto", base_url="https://awx.example",
        auth_token_encrypted=encrypt_token("awx_pat_x"),
        verify_ssl=False, sync_mode="auto", sync_interval_minutes=20,
        created_by_user_id=admin.id,
    ))
    await db.commit()

    monkeypatch.setattr(cfg.settings, "scheduler_enabled", True, raising=True)
    sch._scheduler = None
    sch._is_leader = False
    try:
        await sch.start_scheduler()
        assert sch._is_leader is True
        assert sch._scheduler is not None
        assert sch._scheduler.running is True
        assert "retention" in {j.id for j in sch._scheduler.get_jobs()}
    finally:
        await sch.stop_scheduler()
        assert sch._scheduler is None
        assert sch._is_leader is False


@pytest.mark.db_per_test
async def test_stop_scheduler_releases_lock_even_if_shutdown_raises():
    """Hardening: a failure in scheduler.shutdown() (never fully started / dead event loop) must
    NOT skip releasing the leader advisory lock + closing the connection — otherwise LEADER_KEY
    stays pinned and no worker can ever become leader."""
    import app.scheduler as sch
    from app.db.session import engine

    conn = await engine.connect()
    assert await sch._try_leader_lock(conn) is True

    class _BoomScheduler:
        def shutdown(self, wait=True):
            raise RuntimeError("Event loop is closed")

    sch._scheduler = _BoomScheduler()
    sch._leader_conn = conn
    sch._is_leader = True
    try:
        await sch.stop_scheduler()  # must NOT raise despite shutdown() blowing up
        assert sch._scheduler is None
        assert sch._leader_conn is None
        assert sch._is_leader is False

        # The leader lock is free again: another connection can re-acquire LEADER_KEY.
        other = await engine.connect()
        try:
            assert await sch._try_leader_lock(other) is True
        finally:
            await other.execute(
                text("SELECT pg_advisory_unlock(:k)").bindparams(k=sch.LEADER_KEY)
            )
            await other.commit()
            await other.close()
    finally:
        sch._scheduler = None
        sch._is_leader = False
        if sch._leader_conn is not None:
            await sch._leader_conn.close()
            sch._leader_conn = None


@pytest.mark.db_per_test
async def test_start_scheduler_failure_releases_leader_lock(monkeypatch):
    """Hardening: if registration fails during startup, start_scheduler must release the leader
    lock + reset state (not leave LEADER_KEY pinned with a half-built, never-started scheduler)."""
    import app.scheduler as sch
    from app.core import config as cfg
    from app.db.session import engine

    monkeypatch.setattr(cfg.settings, "scheduler_enabled", True, raising=True)
    sch._scheduler = None
    sch._is_leader = False
    sch._leader_conn = None

    async def _boom(scheduler, db):
        raise RuntimeError("registration failed")

    monkeypatch.setattr(sch, "_register_all", _boom)
    try:
        with pytest.raises(RuntimeError, match="registration failed"):
            await sch.start_scheduler()

        assert sch._scheduler is None          # never assigned a half-built scheduler
        assert sch._is_leader is False
        assert sch._leader_conn is None

        probe = await engine.connect()         # the leader lock was released
        try:
            assert await sch._try_leader_lock(probe) is True
        finally:
            await probe.execute(
                text("SELECT pg_advisory_unlock(:k)").bindparams(k=sch.LEADER_KEY)
            )
            await probe.commit()
            await probe.close()
    finally:
        sch._scheduler = None
        sch._is_leader = False
        if sch._leader_conn is not None:
            await sch._leader_conn.close()
            sch._leader_conn = None
