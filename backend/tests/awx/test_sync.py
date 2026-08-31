from __future__ import annotations

import uuid

import pytest

from app.awx.client import AwxError, JobDetail, JobSummary
from app.awx.sync import sync_controller
from app.core.crypto import encrypt_token
from app.models import AwxController, Run, RunRaw, Task


# ---- a tiny in-memory AWX stub the sync engine talks to (no network) --------

def _job(job_id: int, *, status: str = "successful", launch_type: str = "manual",
         workflow_name: str | None = None) -> JobSummary:
    return JobSummary(
        id=job_id,
        name="Day2Actions",
        status=status,
        started="2026-06-03T10:00:00Z",
        finished="2026-06-03T10:00:11Z",
        elapsed=11.0,
        launch_type=launch_type,
        organization_id=2,
        organization_name="DXC",
        created_by_username="cloudauto",
        workflow_name=workflow_name,
        url=f"/api/v2/jobs/{job_id}/",
    )


# events for one job: a changed task + an unreachable task -> literal-worst 'unreachable'
def _events() -> list[dict]:
    return [
        {"event": "playbook_on_play_start", "counter": 1, "created": "2026-06-03T10:00:01.000000Z",
         "stdout": "PLAY [web] *****\n", "event_data": {"play": "web"}},
        {"event": "playbook_on_task_start", "counter": 2, "created": "2026-06-03T10:00:02.000000Z",
         "stdout": "TASK [Install nginx] *****\n",
         "event_data": {"play": "web", "task": "Install nginx", "role": "webserver"}},
        {"event": "runner_on_ok", "counter": 3, "created": "2026-06-03T10:00:04.000000Z", "host": "web01",
         "stdout": "changed: [web01]\n",
         "event_data": {"task": "Install nginx", "host": "web01", "res": {"changed": True}}},
        {"event": "playbook_on_task_start", "counter": 4, "created": "2026-06-03T10:00:05.000000Z",
         "stdout": "TASK [Restart nginx] *****\n",
         "event_data": {"play": "web", "task": "Restart nginx", "role": "webserver"}},
        {"event": "runner_on_unreachable", "counter": 5, "created": "2026-06-03T10:00:10.000000Z", "host": "web02",
         "stdout": "fatal: [web02]: UNREACHABLE!\n",
         "event_data": {"task": "Restart nginx", "host": "web02",
                        "res": {"unreachable": True, "msg": "No route to host"}}},
        {"event": "playbook_on_stats", "counter": 6, "created": "2026-06-03T10:00:11.000000Z",
         "stdout": "PLAY RECAP *****\n",
         "event_data": {"ok": {"web01": 1}, "changed": {"web01": 1}, "dark": {"web02": 1},
                        "failures": {}, "skipped": {}, "processed": {"web01": 1, "web02": 1}}},
    ]


class FakeAwxClient:
    """Drop-in for AwxClient: fixed job list + per-job events; records nothing to network."""
    def __init__(self, jobs, events_by_id):
        self._jobs = jobs
        self._events = events_by_id
        self.entered = False
        self.last_list_count = None

    def __init_subclass__(cls):  # noqa: D401  (never subclassed; keeps type-checkers quiet)
        ...

    async def __aenter__(self):
        self.entered = True
        return self

    async def __aexit__(self, *exc):
        self.entered = False

    async def list_jobs(self, since_id):
        fresh = [j for j in self._jobs if j.id > since_id]
        self.last_list_count = len(fresh)
        for j in fresh:
            yield j

    async def get_job_events(self, job_id):
        return self._events[job_id]

    async def get_job_detail(self, job_id) -> JobDetail:
        return JobDetail(extra_vars={}, limit=None, scm_revision=None,
                         project_id=None, project_name=None, job_template_id=None, survey=None)

    async def list_projects(self):
        return []


def _patch_client(monkeypatch, jobs, events_by_id):
    """Patch the AwxClient symbol *as imported in sync.py* with the fake (oldest->newest)."""
    def _factory(base_url, token, verify_ssl, **kw):
        return FakeAwxClient(sorted(jobs, key=lambda j: j.id), events_by_id)
    monkeypatch.setattr("app.awx.sync.AwxClient", _factory)


async def _controller(db, *, last_synced_job_id=None) -> AwxController:
    c = AwxController(
        name=f"ctl-{uuid.uuid4().hex[:8]}",
        base_url="https://awx.example.com",
        auth_token_encrypted=encrypt_token("awx_pat_secret"),
        verify_ssl=False,
        last_synced_job_id=last_synced_job_id,
    )
    db.add(c)
    await db.flush()
    return c


async def test_sync_imports_jobs_with_full_mapping(db, monkeypatch):
    c = await _controller(db)
    jobs = [_job(744, status="successful", launch_type="workflow", workflow_name="Nightly"),
            _job(745, status="error")]
    events = {744: _events(), 745: _events()}
    _patch_client(monkeypatch, jobs, events)

    res = await sync_controller(db, c)

    assert res.status == "ok"
    assert res.imported == 2 and res.skipped == 0
    assert res.last_synced_job_id == 745
    # controller cursor + status persisted
    assert c.last_synced_job_id == 745
    assert c.last_sync_status == "ok" and c.status == "connected"
    assert c.last_sync_error is None and c.last_sync_at is not None

    runs = (await db.execute(
        Run.__table__.select().where(Run.controller_id == c.id).order_by(Run.awx_job_id)
    )).all()
    assert len(runs) == 2

    from sqlalchemy import select
    r744 = await db.scalar(select(Run).where(Run.controller_id == c.id, Run.awx_job_id == "744"))
    assert r744.source == "awx"
    assert r744.owner_user_id is None and r744.team_id is None
    assert r744.template_name == "Day2Actions"
    assert r744.awx_user == "cloudauto"
    assert r744.awx_job_url == "https://awx.example.com/api/v2/jobs/744/"
    assert r744.awx_organization_id == 2 and r744.awx_organization_name == "DXC"
    assert r744.awx_launch_type == "workflow" and r744.awx_workflow_name == "Nightly"
    assert r744.status == "unreachable"  # literal-worst over the two tasks
    assert r744.host_count == 2 and r744.task_count == 2

    # tasks present, seq 1..N
    seqs = (await db.execute(
        select(Task.seq).where(Task.run_id == r744.id).order_by(Task.seq)
    )).scalars().all()
    assert seqs == [1, 2]

    # run_raw == joined per-event stdout in counter order
    raw = await db.scalar(select(RunRaw.content).where(RunRaw.run_id == r744.id))
    assert raw == "".join(ev.get("stdout") or "" for ev in _events())
    assert raw.startswith("PLAY [web]") and "UNREACHABLE" in raw


async def test_empty_event_terminal_error_job_is_stored_as_failed(db, monkeypatch):
    """Without the AWX status floor, an error job with no tasks is incorrectly stored as ok."""
    from sqlalchemy import select

    c = await _controller(db)
    _patch_client(monkeypatch, [_job(744, status="error")], {744: []})

    result = await sync_controller(db, c)

    imported = await db.scalar(select(Run).where(Run.controller_id == c.id, Run.awx_job_id == "744"))
    assert result.status == "ok"
    assert imported is not None
    assert imported.status == "failed"
    assert imported.task_count == 0


async def test_per_job_integrity_error_skips_and_refreshes_controller(db, monkeypatch):
    """Drive the per-job IntegrityError branch directly: a pre-existing Run with the same
    (controller_id, awx_job_id) makes the per-job commit conflict on
    uq_runs_controller_id_awx_job_id. The dedupe SELECT is forced to miss (simulating a
    concurrent insert that landed AFTER the dedupe check), so the commit raises
    IntegrityError -> rollback + db.refresh(controller) + skipped++. The cursor still
    advances and the final controller status persists (proving the refreshed instance
    is live, not stale)."""
    from app.models import Run as RunModel

    c = await _controller(db)
    # job 744 already imported (conflicting row), 745 is genuinely new
    pre = RunModel(source="awx", owner_user_id=None, controller_id=c.id,
                   awx_job_id="744", status="ok", recap=[])
    db.add(pre)
    await db.flush()

    jobs = [_job(744), _job(745)]
    events = {744: _events(), 745: _events()}
    _patch_client(monkeypatch, jobs, events)

    # Force the dedupe SELECT to return None for BOTH jobs so 744 reaches the commit and
    # trips the unique constraint (the IntegrityError branch under test). 745 commits clean.
    import app.awx.sync as sync_mod  # noqa: F401
    real_scalar = db.scalar

    async def _scalar_miss_dedupe(stmt, *a, **kw):
        # crude: the dedupe query selects Run.id; pretend nothing exists so we hit the insert
        txt = str(stmt)
        if "runs.id" in txt and "awx_job_id" in txt:
            return None
        return await real_scalar(stmt, *a, **kw)

    monkeypatch.setattr(db, "scalar", _scalar_miss_dedupe)

    res = await sync_controller(db, c)

    assert res.status == "ok"
    assert res.imported == 1            # only 745 actually inserts
    assert res.skipped == 1             # 744 conflicts -> IntegrityError dedupe branch
    assert res.last_synced_job_id == 745
    assert c.last_synced_job_id == 745  # cursor advanced past the conflicting job
    assert c.last_sync_status == "ok" and c.status == "connected"  # stamped on a LIVE instance


async def test_resync_is_idempotent(db, monkeypatch):
    c = await _controller(db)
    jobs = [_job(744), _job(745)]
    events = {744: _events(), 745: _events()}
    _patch_client(monkeypatch, jobs, events)

    first = await sync_controller(db, c)
    assert first.imported == 2 and first.skipped == 0

    # second sync: list_jobs(since=745) yields nothing new in real AWX, but even if the
    # cursor were 0 the dedupe path must skip both. Force the worst case: reset cursor to 0.
    c.last_synced_job_id = 0
    await db.flush()
    second = await sync_controller(db, c)
    assert second.status == "ok"
    assert second.imported == 0 and second.skipped == 2
    assert second.last_synced_job_id == 745
    assert c.last_synced_job_id == 745

    from sqlalchemy import func, select
    n = await db.scalar(
        select(func.count()).select_from(Run).where(Run.controller_id == c.id)
    )
    assert n == 2  # no duplicates created


async def test_cursor_only_advances_from_existing_high_water_mark(db, monkeypatch):
    c = await _controller(db, last_synced_job_id=744)  # already synced up to 744
    jobs = [_job(745)]  # only the new one is past the cursor
    events = {745: _events()}
    _patch_client(monkeypatch, jobs, events)

    res = await sync_controller(db, c)
    assert res.imported == 1 and res.last_synced_job_id == 745
    from sqlalchemy import select
    only = (await db.execute(select(Run.awx_job_id).where(Run.controller_id == c.id))).scalars().all()
    assert only == ["745"]  # 744 was never re-fetched (list_jobs(since=744) skipped it)


class FlakyAwxClient(FakeAwxClient):
    """Raises AwxError on get_job_events for one specific job id."""
    def __init__(self, jobs, events_by_id, fail_on):
        super().__init__(jobs, events_by_id)
        self._fail_on = fail_on

    async def get_job_events(self, job_id):
        if job_id == self._fail_on:
            raise AwxError("AWX returned non-JSON for job_events", status=None)
        return self._events[job_id]


async def test_resume_after_failure_mid_iteration(db, monkeypatch):
    c = await _controller(db)
    jobs = [_job(744), _job(745), _job(746)]
    events = {744: _events(), 745: _events(), 746: _events()}

    # first run: blow up on job 745 (after 744 commits durably)
    def _flaky(base_url, token, verify_ssl, **kw):
        return FlakyAwxClient(sorted(jobs, key=lambda j: j.id), events, fail_on=745)
    monkeypatch.setattr("app.awx.sync.AwxClient", _flaky)

    res1 = await sync_controller(db, c)
    assert res1.status == "error"
    assert res1.imported == 1  # only 744 committed
    assert "non-JSON" in (res1.error or "")
    assert c.last_synced_job_id == 744  # durable cursor at last committed job
    assert c.last_sync_status == "error" and c.status == "error"
    assert c.last_sync_error and "non-JSON" in c.last_sync_error

    from sqlalchemy import select
    got = (await db.execute(
        select(Run.awx_job_id).where(Run.controller_id == c.id).order_by(Run.awx_job_id)
    )).scalars().all()
    assert got == ["744"]

    # rerun: healthy client now; resumes at since=744 -> imports 745 + 746
    _patch_client(monkeypatch, jobs, events)
    res2 = await sync_controller(db, c)
    assert res2.status == "ok"
    assert res2.imported == 2 and res2.skipped == 0
    assert res2.last_synced_job_id == 746 and c.last_synced_job_id == 746
    assert c.last_sync_status == "ok" and c.status == "connected"

    got2 = (await db.execute(
        select(Run.awx_job_id).where(Run.controller_id == c.id).order_by(Run.awx_job_id)
    )).scalars().all()
    assert got2 == ["744", "745", "746"]


async def test_sync_limit_error_leaves_run_absent_and_cursor_unchanged(db, monkeypatch):
    """Catching an event-limit error per job would finalize an incomplete run or advance its cursor."""
    from sqlalchemy import select

    class EventsLimitError(AwxError):
        pass

    c = await _controller(db)
    _patch_client(monkeypatch, [_job(744)], {744: _events()})

    async def _raise_limit(self, job_id):
        raise EventsLimitError("AWX job 744 exceeds the 3 event safety limit; no partial run was imported")

    monkeypatch.setattr(FakeAwxClient, "get_job_events", _raise_limit)

    result = await sync_controller(db, c)

    assert result.status == "error"
    assert await db.scalar(select(Run.id).where(Run.awx_job_id == "744")) is None
    assert c.last_synced_job_id is None


from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.awx.sync import controller_lock_key, release_controller_lock, try_acquire_controller_lock


@pytest.mark.db_per_test
async def test_sync_skips_when_lock_held_elsewhere(engine):
    """A foreign CONNECTION holding the controller lock -> sync returns skipped_locked."""
    Session = async_sessionmaker(bind=engine, expire_on_commit=False)
    async with engine.connect() as holder, Session() as worker:
        c = AwxController(
            name=f"ctl-{uuid.uuid4().hex[:8]}",
            base_url="https://awx.example.com",
            auth_token_encrypted=encrypt_token("awx_pat_secret"),
            verify_ssl=False,
            last_synced_job_id=100,
        )
        worker.add(c)
        await worker.commit()

        key = controller_lock_key(c.id)
        assert await try_acquire_controller_lock(holder, key) is True  # holder grabs it
        try:
            res = await sync_controller(worker, c)
            assert res.status == "skipped_locked"
            assert res.imported == 0 and res.skipped == 0
            assert res.last_synced_job_id == 100  # cursor untouched
            assert c.last_sync_status != "running"  # never flipped to running
        finally:
            await release_controller_lock(holder, key)
            # cleanup the row we committed outside the rollback fixture
            await worker.delete(c)
            await worker.commit()


@pytest.mark.db_per_test
async def test_lock_survives_intervening_session_commits(engine):
    """The connection-pinning fix: the advisory lock must SURVIVE the per-job commits the
    persistence Session makes. Hold the lock on a dedicated connection, run an intervening
    Session.commit() (the thing that could rotate a pooled connection and drop a
    session-on-Session lock), and assert a SEPARATE connection STILL cannot acquire it.
    Then release and prove it is re-acquirable."""
    Session = async_sessionmaker(bind=engine, expire_on_commit=False)
    key = controller_lock_key(uuid.uuid4())
    async with engine.connect() as lock_conn, Session() as work, engine.connect() as probe:
        assert await try_acquire_controller_lock(lock_conn, key) is True

        # simulate the per-job persistence churn: a real commit on the work session
        await work.execute(text("SELECT 1"))
        await work.commit()
        await work.execute(text("SELECT 1"))
        await work.commit()

        # the lock is bound to lock_conn, not the work session -> still held
        assert await try_acquire_controller_lock(probe, key) is False

        await release_controller_lock(lock_conn, key)
        assert await try_acquire_controller_lock(probe, key) is True  # now free
        await release_controller_lock(probe, key)


async def test_non_terminal_job_holds_cursor_below_it_and_is_refetched_when_terminal(db, monkeypatch):
    """A non-terminal job must NOT be leapfrogged by a higher-id terminal job in the same window:
    the persisted cursor is held just below the non-terminal id so it is re-listed (not permanently
    lost) on the next sync, and imported once it reaches a terminal state.

    Sync 1: AWX returns job 744 (status='new') then 745 (status='successful').
      -> only 745 imported; cursor held at 743 (NOT advanced past the still-pending 744).
    Sync 2: 744 is now 'successful' (745 already imported).
      -> 744 is re-listed and imported; 745 deduped; cursor advances to 745."""
    from sqlalchemy import select

    c = await _controller(db)

    # --- sync 1: 744 non-terminal, 745 terminal (ascending window) ---
    _patch_client(monkeypatch, [_job(744, status="new"), _job(745, status="successful")],
                  {744: [], 745: _events()})
    res1 = await sync_controller(db, c)
    assert res1.status == "ok"
    assert res1.imported == 1                 # only 745
    assert res1.last_synced_job_id == 743     # held below the skipped non-terminal 744 (NOT 745)
    assert c.last_synced_job_id == 743
    after1 = (await db.execute(
        select(Run.awx_job_id).where(Run.controller_id == c.id)
    )).scalars().all()
    assert after1 == ["745"]                  # 744 not imported yet — but it is NOT lost

    # --- sync 2: 744 has finished ('successful'); cursor=743 re-lists it ---
    _patch_client(monkeypatch, [_job(744, status="successful"), _job(745, status="successful")],
                  {744: _events(), 745: _events()})
    res2 = await sync_controller(db, c)
    assert res2.status == "ok"
    assert res2.imported == 1                  # 744 now imported
    assert res2.skipped == 1                   # 745 deduped (already present)
    assert res2.last_synced_job_id == 745      # cursor now advances past both
    assert c.last_synced_job_id == 745
    after2 = sorted((await db.execute(
        select(Run.awx_job_id).where(Run.controller_id == c.id)
    )).scalars().all())
    assert after2 == ["744", "745"]            # 744 recovered, no duplicate of 745


async def test_sync_reports_progress_then_resets(db, monkeypatch):
    c = await _controller(db)
    jobs = [_job(744), _job(745), _job(746)]
    events = {744: _events(), 745: _events(), 746: _events()}
    _patch_client(monkeypatch, jobs, events)

    # match_run runs right after each per-job commit; snapshot progress there.
    snaps: list[tuple[int | None, int | None, str | None]] = []

    async def _spy(db_, run_):
        snaps.append((c.sync_done, c.sync_total, c.sync_current_job))

    monkeypatch.setattr("app.awx.sync.match_run", _spy)

    res = await sync_controller(db, c)

    assert res.status == "ok" and res.imported == 3
    # progressed 1->2->3 against a total of 3, naming the current job each time
    assert snaps == [(1, 3, "744"), (2, 3, "745"), (3, 3, "746")]
    # cleared after a successful sync
    assert c.sync_total is None and c.sync_done is None and c.sync_current_job is None


async def test_sync_clears_progress_on_error(db, monkeypatch):
    c = await _controller(db)
    jobs = [_job(744)]
    events = {744: _events()}
    _patch_client(monkeypatch, jobs, events)

    async def _boom(self, job_id):
        raise AwxError("events fetch failed")

    monkeypatch.setattr(FakeAwxClient, "get_job_events", _boom)

    res = await sync_controller(db, c)

    assert res.status == "error"
    assert c.last_sync_status == "error"
    assert c.sync_total is None and c.sync_done is None and c.sync_current_job is None
