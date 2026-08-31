"""AWX sync stores job.started -> Run.launched_at; uploads leave it null."""
from __future__ import annotations

import pytest
from cryptography.fernet import Fernet
from pydantic import SecretStr
from sqlalchemy import select

from app.awx import sync as sync_mod
from app.awx.client import JobDetail, JobSummary
from app.awx.sync import _parse_iso, sync_controller
from app.core.config import settings
from app.core.crypto import encrypt_token
from app.models import AwxController, Run

pytestmark = pytest.mark.asyncio

_STARTED = "2026-06-03T10:00:00Z"


@pytest.fixture
def _awx_token_enc_key(monkeypatch):
    key = Fernet.generate_key().decode()
    monkeypatch.setattr(settings, "token_enc_key", SecretStr(key))
    return key


def _job(job_id: int) -> JobSummary:
    return JobSummary(
        id=job_id, name="TestTemplate", status="successful",
        started=_STARTED,
        finished="2026-06-03T10:00:43Z", elapsed=43.0,
        launch_type="manual", organization_id=1, organization_name="Ops",
        created_by_username="bot", workflow_name=None,
        url=f"/api/v2/jobs/{job_id}/",
    )


def _events() -> list[dict]:
    return [
        {"event": "playbook_on_play_start", "counter": 1,
         "created": "2026-06-03T10:00:01.000000Z", "stdout": "PLAY [all] ***\n",
         "event_data": {"play": "all"}},
        {"event": "playbook_on_stats", "counter": 2,
         "created": "2026-06-03T10:00:43.000000Z", "stdout": "PLAY RECAP ***\n",
         "event_data": {"ok": {"h1": 1}, "changed": {}, "dark": {},
                        "failures": {}, "skipped": {}, "processed": {"h1": 1}}},
    ]


class _FakeClient:
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


async def test_sync_sets_launched_at_from_started(db, monkeypatch, _awx_token_enc_key):
    ctrl = AwxController(name="launch-ctrl", base_url="https://awx.example",
                         auth_token_encrypted=encrypt_token("tok"))
    db.add(ctrl)
    await db.flush()

    fake = _FakeClient([_job(300)], {300: _events()})
    monkeypatch.setattr(sync_mod, "AwxClient", lambda *a, **k: fake)

    result = await sync_controller(db, ctrl)
    assert result.status == "ok" and result.imported == 1

    run = await db.scalar(select(Run).where(Run.controller_id == ctrl.id, Run.awx_job_id == "300"))
    assert run is not None
    assert run.launched_at == _parse_iso(_STARTED)
