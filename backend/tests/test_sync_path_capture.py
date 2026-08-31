# backend/tests/test_sync_path_capture.py
import pytest
from cryptography.fernet import Fernet
from pydantic import SecretStr
from sqlalchemy import select
from app.awx import sync as sync_mod
from app.awx.client import JobSummary, JobDetail
from app.awx.sync import sync_controller
from app.core.config import settings
from app.core.crypto import encrypt_token
from app.models import AwxController, Run, RunNode, RunNodeResult

pytestmark = pytest.mark.asyncio


@pytest.fixture
def _enc_key(monkeypatch):
    monkeypatch.setattr(settings, "token_enc_key", SecretStr(Fernet.generate_key().decode()))


def _job(jid):
    return JobSummary(id=jid, name="Day2", status="successful", started="2026-06-03T10:00:00Z",
                      finished="2026-06-03T10:00:05Z", elapsed=5.0, launch_type="manual",
                      organization_id=1, organization_name="Ops", created_by_username="bot",
                      workflow_name=None, url=f"/api/v2/jobs/{jid}/")


def _events():
    return [
        {"event": "playbook_on_play_start", "counter": 1, "created": "2026-06-03T10:00:01Z",
         "event_data": {"play": "p", "play_uuid": "play-1"}},
        {"event": "playbook_on_task_start", "counter": 2, "created": "2026-06-03T10:00:02Z",
         "event_data": {"task": "t1", "task_uuid": "t-1", "play_uuid": "play-1",
                        "task_action": "ansible.builtin.debug", "task_path": "/runner/project/main.yaml:5"}},
        {"event": "runner_on_ok", "counter": 3, "created": "2026-06-03T10:00:03Z",
         "event_data": {"task_uuid": "t-1", "host": "h1", "duration": 1.0, "res": {"changed": False}}},
        {"event": "playbook_on_stats", "counter": 4, "created": "2026-06-03T10:00:05Z",
         "event_data": {"ok": {"h1": 1}, "processed": {"h1": 1}}},
    ]


class _Fake:
    async def __aenter__(self): return self
    async def __aexit__(self, *e): return False
    async def list_jobs(self, since):
        for j in [_job(900)]:
            if j.id > since: yield j
    async def get_job_events(self, jid): return _events()
    async def get_job_detail(self, jid):
        return JobDetail(extra_vars={"target_env": "prod"}, limit="batch_3",
                         scm_revision="abc123", project_id=7, project_name="day2",
                         job_template_id=12, survey=None)

    async def list_projects(self):
        return []


async def test_sync_captures_tree_and_inputs(db, monkeypatch, _enc_key):
    ctrl = AwxController(name="c", base_url="https://awx.example",
                         auth_token_encrypted=encrypt_token("t"))
    db.add(ctrl); await db.flush()
    monkeypatch.setattr(sync_mod, "AwxClient", lambda *a, **k: _Fake())

    res = await sync_controller(db, ctrl)
    assert res.status == "ok" and res.imported == 1

    run = await db.scalar(select(Run).where(Run.awx_job_id == "900"))
    assert run.extra_vars == {"target_env": "prod"} and run.awx_limit == "batch_3"
    assert run.scm_revision == "abc123" and run.project_id == 7 and run.job_template_id == 12
    nodes = (await db.execute(select(RunNode).where(RunNode.run_id == run.id))).scalars().all()
    results = (await db.execute(select(RunNodeResult).where(RunNodeResult.run_id == run.id))).scalars().all()
    assert any(n.node_type == "task" and n.name == "t1" for n in nodes)
    assert any(r.host == "h1" for r in results)
