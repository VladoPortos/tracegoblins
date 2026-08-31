"""Opt-in integration tests against a LIVE AWX 24.6.1.

Runs only when AWX_TEST_URL/AWX_TEST_TOKEN are set (the dev instance is documented
in memory `awx-dev-instance`); skipped + CI-safe otherwise. Never hardcodes a token.

Consolidated from the former tests/test_awx_real_integration.py (deleted) — unique
tests folded in here; the duplicate ping test was omitted.
"""
import json
import os
import uuid

import pytest
from sqlalchemy import select

from app.awx.client import AwxClient, JobSummary
from app.awx.sync import sync_controller
from app.core.crypto import encrypt_token
from app.logparser import parse_job_events
from app.logparser.models import ParsedRun
from app.models import AwxController, Run, RunRaw, Task

pytestmark = pytest.mark.skipif(
    not os.getenv("AWX_TEST_URL"),
    reason="set AWX_TEST_URL/AWX_TEST_TOKEN to run the live AWX integration test",
)

AWX_URL = os.getenv("AWX_TEST_URL", "")
AWX_TOKEN = os.getenv("AWX_TEST_TOKEN", "")
# Dev AWX is self-signed -> verify must be off for the integration run.
VERIFY = os.getenv("AWX_TEST_VERIFY", "false").lower() in ("1", "true", "yes")

# Well-known job IDs on the dev instance (from the former test_awx_real_integration.py)
_JOB_FAILED = 745       # runner_on_failed assertion
_JOB_SUCCESS = 743      # successful multi-host run


async def test_real_ping_reports_version_and_identity():
    async with AwxClient(AWX_URL, AWX_TOKEN, verify_ssl=VERIFY) as client:
        out = await client.ping()
    assert out["version"], "AWX ping returned no version"
    assert out["version"].startswith("24."), f"unexpected AWX version {out['version']!r}"
    assert out["identity"], "AWX /me/ returned no identity (check the token)"


async def test_real_list_jobs_yields_finished_job_summaries():
    async with AwxClient(AWX_URL, AWX_TOKEN, verify_ssl=VERIFY) as client:
        first = None
        async for js in client.list_jobs(0):
            first = js
            break
    assert isinstance(first, JobSummary), "no jobs visible to this token"
    assert first.status in ("successful", "failed", "error", "canceled")
    assert first.id > 0


async def test_real_one_job_events_parse_with_adapter():
    async with AwxClient(AWX_URL, AWX_TOKEN, verify_ssl=VERIFY) as client:
        target = None
        async for js in client.list_jobs(0):
            target = js
            break
        assert target is not None, "no job to fetch events for"
        events = await client.get_job_events(target.id)
    assert events, f"job {target.id} returned no events"
    run = parse_job_events(events)
    assert isinstance(run, ParsedRun)
    assert run.plays, f"job {target.id}: adapter parsed no plays from real events"
    assert run.task_count >= 0


async def test_real_sync_persists_one_awx_run(db):
    # One-job real sync through the PRODUCTION sync_controller, capped to a single job by
    # seeding the cursor to (newest_id - 1) so only the most-recent job imports — keeps the
    # integration test fast + bounded while exercising the full encrypt->decrypt->adapter
    # ->persist chain against real Day2Actions job_events.
    async with AwxClient(AWX_URL, AWX_TOKEN, verify_ssl=False) as c:
        ids = []
        async for job in c.list_jobs(since_id=0):
            ids.append(job.id)
            if len(ids) >= 50:
                break
    assert ids, "no finished jobs on the dev AWX"
    newest = max(ids)

    controller = AwxController(
        id=uuid.uuid4(),
        name=f"real-awx-{uuid.uuid4().hex[:8]}",
        base_url=AWX_URL,
        auth_token_encrypted=encrypt_token(AWX_TOKEN),
        verify_ssl=False,
        sync_mode="manual",
        last_synced_job_id=newest - 1,  # only the newest job imports
    )
    db.add(controller)
    await db.commit()

    result = await sync_controller(db, controller)
    assert result.status == "ok", result.error
    assert result.imported == 1
    assert result.last_synced_job_id == newest

    run = await db.scalar(
        select(Run).where(Run.controller_id == controller.id, Run.awx_job_id == str(newest))
    )
    assert run is not None
    assert run.source == "awx"
    assert run.template_name  # real template name (Day2Actions)
    assert run.awx_organization_name  # real org
    # the run carries tasks + raw built by the M2 job_events adapter
    tasks = (await db.scalars(select(Task).where(Task.run_id == run.id))).all()
    assert len(tasks) >= 1
    raw = await db.scalar(select(RunRaw).where(RunRaw.run_id == run.id))
    assert raw is not None and len(raw.content) > 0

    # re-sync is idempotent (dedupe): nothing new imports.
    controller.last_synced_job_id = newest - 1
    await db.commit()
    again = await sync_controller(db, controller)
    assert again.imported == 0
    assert again.skipped >= 1


async def test_real_get_job_events_failed_job() -> None:
    """Fetch real job_events for the known-failed job and assert the parsed tree."""
    async with AwxClient(AWX_URL, AWX_TOKEN, verify_ssl=False) as client:
        events = await client.get_job_events(_JOB_FAILED)

    assert isinstance(events, list)
    assert len(events) > 0, "Expected at least one event"

    # Must contain at least one playbook_on_stats (recap present)
    event_types = {e.get("event", "") for e in events}
    assert "playbook_on_stats" in event_types
    assert "runner_on_failed" in event_types

    # Parse with the adapter
    run = parse_job_events(events)

    # Play tree
    assert len(run.plays) >= 1
    assert run.task_count > 0

    # All host keys must be strings (catches the int-host drift)
    bad_hosts = [
        (t.name, h)
        for p in run.plays
        for t in p.tasks
        for h in t.statuses
        if not isinstance(h, str)
    ]
    assert bad_hosts == [], f"Non-string host keys in parsed run: {bad_hosts}"

    # There must be at least one failed task with error detail
    failed_tasks = [
        t
        for p in run.plays
        for t in p.tasks
        if "failed" in t.statuses.values()
    ]
    assert failed_tasks, "Expected at least one failed task"
    ft = failed_tasks[0]
    assert ft.error is not None, "Failed task must carry error JSON"
    err = json.loads(ft.error)
    assert "msg" in err, "error blob must have a msg field"

    # Recap from playbook_on_stats
    assert run.recap, "Expected a non-empty recap"
    total_failed = sum(r.failed for r in run.recap)
    assert total_failed >= 1, "Recap must show at least one failure"


async def test_real_get_job_events_successful_job() -> None:
    """Fetch real job_events for the known-successful job and assert the parsed tree."""
    async with AwxClient(AWX_URL, AWX_TOKEN, verify_ssl=False) as client:
        events = await client.get_job_events(_JOB_SUCCESS)

    assert isinstance(events, list)
    assert len(events) > 100, "Successful job should have many events"

    run = parse_job_events(events)

    # Multiple plays expected
    assert len(run.plays) >= 2
    assert run.task_count > 50

    # No failures
    failed = [
        t
        for p in run.plays
        for t in p.tasks
        if "failed" in t.statuses.values()
    ]
    assert failed == [], f"Unexpected failures in successful job: {[t.name for t in failed]}"

    # Recap: two hosts, no failures
    recap = {r.host: r for r in run.recap}
    assert "localhost" in recap
    total_failed = sum(r.failed for r in run.recap)
    assert total_failed == 0

    # All host keys are strings
    bad_hosts = [
        (t.name, h)
        for p in run.plays
        for t in p.tasks
        for h in t.statuses
        if not isinstance(h, str)
    ]
    assert bad_hosts == [], f"Non-string host keys: {bad_hosts}"
