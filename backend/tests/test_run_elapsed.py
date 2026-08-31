"""Fix A — Run.elapsed: AWX sync stores float seconds; uploads leave it null.

Tests:
  1. AWX-synced run card carries elapsed as a float.
  2. Personal upload run card has elapsed=None.
  3. Migration roundtrip: column exists in DB with correct nullable+type.
"""
from __future__ import annotations

import pytest
from cryptography.fernet import Fernet
from pydantic import SecretStr
from sqlalchemy import select, text

from app.awx import sync as sync_mod
from app.awx.client import JobDetail, JobSummary
from app.awx.sync import sync_controller
from app.core.config import settings
from app.core.crypto import encrypt_token
from app.models import AwxController, Run
from app.services.runs_query import run_to_card

pytestmark = pytest.mark.asyncio


@pytest.fixture
def _awx_token_enc_key(monkeypatch):
    """Fernet key on settings so encrypt_token/decrypt_token round-trip in tests."""
    key = Fernet.generate_key().decode()
    monkeypatch.setattr(settings, "token_enc_key", SecretStr(key))
    return key

_ELAPSED = 42.5


def _job(job_id: int) -> JobSummary:
    return JobSummary(
        id=job_id, name="TestTemplate", status="successful",
        started="2026-06-04T10:00:01Z",
        finished="2026-06-04T10:00:43Z", elapsed=_ELAPSED,
        launch_type="manual", organization_id=1, organization_name="Ops",
        created_by_username="bot", workflow_name=None,
        url=f"/api/v2/jobs/{job_id}/",
    )


def _events() -> list[dict]:
    return [
        {"event": "playbook_on_play_start", "counter": 1,
         "created": "2026-06-04T10:00:01.000000Z", "stdout": "PLAY [all] ***\n",
         "event_data": {"play": "all"}},
        {"event": "playbook_on_task_start", "counter": 2,
         "created": "2026-06-04T10:00:02.000000Z", "stdout": "TASK [Ping] ***\n",
         "event_data": {"play": "all", "task": "Ping", "role": None}},
        {"event": "runner_on_ok", "counter": 3,
         "created": "2026-06-04T10:00:03.000000Z", "host": "host01",
         "stdout": "ok: [host01]\n",
         "event_data": {"task": "Ping", "host": "host01", "res": {"changed": False}}},
        {"event": "playbook_on_stats", "counter": 4,
         "created": "2026-06-04T10:00:43.000000Z", "stdout": "PLAY RECAP ***\n",
         "event_data": {"ok": {"host01": 1}, "changed": {}, "dark": {},
                        "failures": {}, "skipped": {}, "processed": {"host01": 1}}},
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


async def test_awx_synced_run_card_carries_elapsed(db, monkeypatch, _awx_token_enc_key):
    """An AWX-synced run must have elapsed=42.5 on its card."""
    ctrl = AwxController(
        name="elapsed-ctrl", base_url="https://awx.example",
        auth_token_encrypted=encrypt_token("tok"),
    )
    db.add(ctrl)
    await db.flush()

    fake = _FakeClient([_job(200)], {200: _events()})
    monkeypatch.setattr(sync_mod, "AwxClient", lambda *a, **k: fake)

    result = await sync_controller(db, ctrl)
    assert result.status == "ok" and result.imported == 1

    run = await db.scalar(select(Run).where(Run.controller_id == ctrl.id, Run.awx_job_id == "200"))
    assert run is not None
    assert run.elapsed == _ELAPSED

    card = run_to_card(run)
    assert isinstance(card.elapsed, float)
    assert card.elapsed == _ELAPSED


async def test_upload_run_card_has_elapsed_none(db, make_user):
    """A personal-upload run must have elapsed=None on its card."""
    user = await make_user(email="elapsed_upload@example.com")
    run = Run(source="upload", owner_user_id=user.id, status="ok",
              host_count=0, task_count=0, warnings_count=0, recap=[])
    db.add(run)
    await db.flush()

    run = await db.scalar(select(Run).where(Run.id == run.id))
    assert run.elapsed is None
    card = run_to_card(run)
    assert card.elapsed is None


async def test_elapsed_column_exists_nullable_in_db(db):
    """DB column 'elapsed' on 'runs' is present and nullable (migration roundtrip)."""
    row = await db.execute(
        text(
            "SELECT data_type, is_nullable FROM information_schema.columns "
            "WHERE table_name='runs' AND column_name='elapsed'"
        )
    )
    r = row.one()
    assert r.is_nullable == "YES"
    assert "float" in r.data_type.lower() or "double" in r.data_type.lower() or "real" in r.data_type.lower()
