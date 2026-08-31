from __future__ import annotations

import uuid
from datetime import datetime, timezone

from app.models import AwxController, ControllerTeam, Run, Team


async def test_run_detail_exposes_awx_fields(client, db, make_user, session_for):
    team = Team(name="DetailTeam", slug=f"dt-{uuid.uuid4().hex[:6]}")
    db.add(team)
    await db.flush()
    member = await make_user(email=f"d-{uuid.uuid4().hex[:6]}@example.com", team=team)
    ctrl = AwxController(name=f"det-{uuid.uuid4().hex[:6]}", base_url="https://awx.example",
                         auth_token_encrypted="gAAAAAFake==")
    db.add(ctrl)
    await db.flush()
    db.add(ControllerTeam(controller_id=ctrl.id, team_id=team.id))
    run = Run(source="awx", owner_user_id=member.id, controller_id=ctrl.id,
              awx_job_id="745", status="failed", awx_organization_id=2,
              awx_organization_name="DXC", awx_launch_type="workflow",
              awx_workflow_name="NightlyFlow", template_name="Day2Actions",
              log_time=datetime.now(timezone.utc))
    db.add(run)
    await db.flush()

    mc = await session_for(member)
    r = await mc.get(f"/api/runs/{run.id}")
    assert r.status_code == 200
    body = r.json()
    assert body["awx_organization_name"] == "DXC"
    assert body["awx_launch_type"] == "workflow"
    assert body["controller_id"] == str(ctrl.id)
    assert body["controller_name"] == ctrl.name


async def test_run_detail_upload_has_null_awx_fields(authed_client):
    from pathlib import Path
    root = Path(__file__).resolve().parents[2]
    txt = (root / "backend/tests/fixtures/logs/job_11140.txt").read_text(encoding="utf-8")
    cr = await authed_client.post("/api/runs", json={"text": txt})
    rid = cr.json()["id"]
    body = (await authed_client.get(f"/api/runs/{rid}")).json()
    assert body["awx_organization_name"] is None
    assert body["awx_launch_type"] is None
    assert body["controller_id"] is None
    assert body["controller_name"] is None
