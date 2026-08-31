from __future__ import annotations

import pytest
from sqlalchemy import func, select

from app.awx import sync as sync_mod
from app.awx.client import JobDetail, JobSummary
from app.awx.sync import sync_controller
from app.core.crypto import encrypt_token
from app.models import (
    AwxController, ControllerTeam, KbOccurrence, KbSignature, Run, Team,
)

pytestmark = pytest.mark.asyncio


def _job(job_id: int) -> JobSummary:
    return JobSummary(
        id=job_id, name="Day2Actions", status="failed",
        started="2026-06-03T10:00:00Z",
        finished="2026-06-03T10:00:11Z", elapsed=11.0,
        launch_type="manual", organization_id=2, organization_name="DXC",
        created_by_username="cloudauto", workflow_name=None,
        url=f"/api/v2/jobs/{job_id}/",
    )


def _events() -> list[dict]:
    # One unreachable task whose res carries the SSH-connect error blob.
    return [
        {"event": "playbook_on_play_start", "counter": 1,
         "created": "2026-06-03T10:00:01.000000Z", "stdout": "PLAY [all] ***\n",
         "event_data": {"play": "all"}},
        {"event": "playbook_on_task_start", "counter": 2,
         "created": "2026-06-03T10:00:02.000000Z", "stdout": "TASK [Connect] ***\n",
         "event_data": {"play": "all", "task": "Connect", "role": None}},
        {"event": "runner_on_unreachable", "counter": 3,
         "created": "2026-06-03T10:00:10.000000Z", "host": "host01",
         "stdout": "fatal: [host01]: UNREACHABLE!\n",
         "event_data": {"task": "Connect", "host": "host01",
                        "res": {"changed": False, "unreachable": True,
                                "msg": "Failed to connect to the host via ssh: "
                                       "Warning: Permanently added '100.66.0.108' "
                                       "(ED25519) to the list of known hosts.\n"
                                       "Load key \"/tmp/ansible._7oamnkx_ssh_cert\": "
                                       "invalid format"}}},
        {"event": "playbook_on_stats", "counter": 4,
         "created": "2026-06-03T10:00:11.000000Z", "stdout": "PLAY RECAP ***\n",
         "event_data": {"ok": {}, "changed": {}, "dark": {"host01": 1},
                        "failures": {}, "skipped": {}, "processed": {"host01": 1}}},
    ]


class _FakeAwxClient:
    def __init__(self, jobs, events_by_id):
        self._jobs = jobs
        self._events = events_by_id

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def list_jobs(self, since: int):
        for j in self._jobs:
            if j.id > since:
                yield j

    async def get_job_events(self, job_id: int):
        return self._events[job_id]

    async def get_job_detail(self, job_id: int) -> JobDetail:
        return JobDetail(extra_vars={}, limit=None, scm_revision=None,
                         project_id=None, project_name=None, job_template_id=None, survey=None)

    async def list_projects(self):
        return []


async def test_sync_records_kb_occurrence(db, monkeypatch, _awx_token_enc_key):
    team = Team(name="SyncKB", slug="synckb")
    db.add(team)
    await db.flush()
    ctrl = AwxController(name="ctrl-synckb", base_url="https://awx.example",
                         auth_token_encrypted=encrypt_token("secret-token"))
    db.add(ctrl)
    await db.flush()
    db.add(ControllerTeam(controller_id=ctrl.id, team_id=team.id, awx_organization_id=None))
    sig = KbSignature(
        team_id=team.id, signature_key="ssh_connection_failed", title="SSH down",
        category="connectivity", status="known-issue",
        representative_text="failed to connect to the host via ssh",
    )
    db.add(sig)
    await db.flush()

    fake = _FakeAwxClient([_job(101)], {101: _events()})
    monkeypatch.setattr(sync_mod, "AwxClient", lambda *a, **k: fake)

    result = await sync_controller(db, ctrl)
    assert result.status == "ok" and result.imported == 1

    run = await db.scalar(select(Run).where(Run.controller_id == ctrl.id, Run.awx_job_id == "101"))
    assert run is not None
    n = await db.scalar(
        select(func.count()).select_from(KbOccurrence)
        .where(KbOccurrence.run_id == run.id, KbOccurrence.signature_id == sig.id)
    )
    assert n == 1
