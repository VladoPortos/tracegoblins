from __future__ import annotations

import uuid
from datetime import datetime, timezone

from app.models import AwxController, ControllerTeam, Run, Team


async def _ctrl(db, name):
    c = AwxController(name=name, base_url="https://awx.example",
                      auth_token_encrypted="gAAAAAFake==")
    db.add(c)
    await db.flush()
    return c


async def test_facets_scoped_to_visible_runs(client, db, make_user, session_for):
    team = Team(name="FacetTeam", slug=f"fc-{uuid.uuid4().hex[:6]}")
    db.add(team)
    await db.flush()
    member = await make_user(email=f"fa-{uuid.uuid4().hex[:6]}@example.com", team=team)
    ctrl = await _ctrl(db, f"facets-{uuid.uuid4().hex[:6]}")
    db.add(ControllerTeam(controller_id=ctrl.id, team_id=team.id))
    await db.flush()
    now = datetime.now(timezone.utc)
    db.add(Run(source="awx", owner_user_id=member.id, controller_id=ctrl.id,
               awx_job_id="1", status="failed", awx_organization_id=2, awx_organization_name="DXC",
               template_name="Day2Actions", awx_user="cloudauto", awx_launch_type="manual",
               log_time=now))
    db.add(Run(source="awx", owner_user_id=member.id, controller_id=ctrl.id,
               awx_job_id="2", status="successful", awx_organization_id=2, awx_organization_name="DXC",
               template_name="Provision", awx_user="bob", awx_launch_type="scheduled",
               log_time=now))
    await db.flush()

    mc = await session_for(member)
    r = await mc.get("/api/runs/filters?scope=team")
    assert r.status_code == 200
    body = r.json()
    assert {o["id"] for o in body["organizations"]} == {2}
    assert body["organizations"][0]["name"] == "DXC"
    assert set(body["templates"]) == {"Day2Actions", "Provision"}
    assert {c["id"] for c in body["controllers"]} == {str(ctrl.id)}
    assert set(body["statuses"]) == {"failed", "successful"}
    assert set(body["launch_types"]) == {"manual", "scheduled"}
    assert set(body["users"]) == {"cloudauto", "bob"}


async def test_facets_empty_for_outsider(client, db, make_user, session_for):
    outsider = await make_user(email=f"fo-{uuid.uuid4().hex[:6]}@example.com")
    oc = await session_for(outsider)
    r = await oc.get("/api/runs/filters?scope=team")
    assert r.status_code == 200
    body = r.json()
    assert body["organizations"] == [] and body["templates"] == [] and body["controllers"] == []
