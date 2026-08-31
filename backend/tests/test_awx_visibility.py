from __future__ import annotations

import uuid

from app.models import AwxController, ControllerTeam, Run, RunShare, Team
from app.services.visibility import is_run_visible


async def _general(db):
    from sqlalchemy import select
    t = await db.scalar(select(Team).where(Team.is_default.is_(True)))
    if t is None:
        t = Team(name="General", slug="general", is_default=True)
        db.add(t)
        await db.flush()
    return t


async def _team(db, name):
    t = Team(name=name, slug=name.lower())
    db.add(t)
    await db.flush()
    return t


async def _controller(db):
    c = AwxController(
        name=f"ctl-{uuid.uuid4().hex[:8]}",
        base_url="https://awx.example.com",
        auth_token_encrypted="gAAAAAFake==",
        verify_ssl=False,
    )
    db.add(c)
    await db.flush()
    return c


async def _awx_run(db, controller, *, org_id):
    r = Run(
        source="awx", owner_user_id=None, team_id=None,
        controller_id=controller.id, awx_job_id=str(uuid.uuid4().int % 100000),
        awx_organization_id=org_id, awx_organization_name="DXC" if org_id else None,
        status="failed",
    )
    db.add(r)
    await db.flush()
    return r


async def test_member_of_assigned_allorgs_team_sees_awx_run(db, make_user):
    team = await _team(db, "Ops")
    user = await make_user(email="ops@example.com", team=team)
    c = await _controller(db)
    db.add(ControllerTeam(controller_id=c.id, team_id=team.id, awx_organization_id=None))  # all orgs
    await db.flush()
    run = await _awx_run(db, c, org_id=2)
    assert await is_run_visible(db, run, user) is True


async def test_org_scoped_team_sees_only_matching_org(db, make_user):
    team = await _team(db, "OrgA")
    user = await make_user(email="orga@example.com", team=team)
    c = await _controller(db)
    db.add(ControllerTeam(controller_id=c.id, team_id=team.id, awx_organization_id=2))  # org 2 only
    await db.flush()
    run_org2 = await _awx_run(db, c, org_id=2)
    run_org9 = await _awx_run(db, c, org_id=9)
    assert await is_run_visible(db, run_org2, user) is True
    assert await is_run_visible(db, run_org9, user) is False  # org-B run not visible


async def test_allorgs_assignment_sees_every_org(db, make_user):
    team = await _team(db, "OpsAll")
    user = await make_user(email="opsall@example.com", team=team)
    c = await _controller(db)
    db.add(ControllerTeam(controller_id=c.id, team_id=team.id, awx_organization_id=None))
    await db.flush()
    assert await is_run_visible(db, await _awx_run(db, c, org_id=2), user) is True
    assert await is_run_visible(db, await _awx_run(db, c, org_id=9), user) is True


async def test_a1_admin_and_non_team_user_cannot_see_awx_run(db, make_user):
    """A1: no controller_teams path -> not visible, even for an admin."""
    team = await _team(db, "Assigned")
    c = await _controller(db)
    db.add(ControllerTeam(controller_id=c.id, team_id=team.id, awx_organization_id=None))
    await db.flush()
    run = await _awx_run(db, c, org_id=2)
    # admin who is NOT in the assigned team (only in General) -> not visible
    admin = await make_user(email="adminx@example.com", role="admin")
    assert await is_run_visible(db, run, admin) is False
    # plain user not in the assigned team -> not visible
    stranger = await make_user(email="stranger@example.com")
    assert await is_run_visible(db, run, stranger) is False


async def test_shared_awx_run_visible_via_run_shares(db, make_user):
    """An AWX run shared to a user's team is visible via branch 4 (controller_teams not required)."""
    team = await _team(db, "Shared")
    user = await make_user(email="shared@example.com", team=team)
    c = await _controller(db)
    # NO controller_teams assignment for this team -> 5th branch can't match
    run = await _awx_run(db, c, org_id=2)
    assert await is_run_visible(db, run, user) is False
    db.add(RunShare(run_id=run.id, shared_with_team_id=team.id, shared_by_user_id=user.id))
    await db.flush()
    assert await is_run_visible(db, run, user) is True  # branch 4 grants it


async def test_awx_run_http_gates_404_for_non_assigned_visible_for_member(
    db, client, session_for, make_user
):
    """A1 at the HTTP layer: non-assigned user -> 404 on run + /tasks + /raw; member -> 200."""
    from app.models import RunRaw, Task

    team = await _team(db, "HttpOps")
    member = await make_user(email="httpops@example.com", team=team)
    c = await _controller(db)
    db.add(ControllerTeam(controller_id=c.id, team_id=team.id, awx_organization_id=None))
    await db.flush()
    run = await _awx_run(db, c, org_id=2)
    # give the run one task + raw so /tasks and /raw have content to serve
    db.add(Task(run_id=run.id, seq=1, play_name="web", name="Install nginx", status="failed", hosts={}))
    db.add(RunRaw(run_id=run.id, content="PLAY RECAP *****\n"))
    await db.flush()
    rid = str(run.id)

    # non-assigned admin -> 404 everywhere (A1) — including individual task detail
    admin = await make_user(email="httpadmin@example.com", role="admin")
    ac = await session_for(admin)
    for path in (
        f"/api/runs/{rid}",
        f"/api/runs/{rid}/tasks",
        f"/api/runs/{rid}/tasks/1",
        f"/api/runs/{rid}/raw",
    ):
        assert (await ac.get(path)).status_code == 404, path

    # non-member non-admin also 404s (A1 independent of role)
    stranger = await make_user(email="httpstranger@example.com")
    sc = await session_for(stranger)
    assert (await sc.get(f"/api/runs/{rid}")).status_code == 404

    # assigned member -> 200 everywhere
    mc = await session_for(member)
    assert (await mc.get(f"/api/runs/{rid}")).status_code == 200
    tasks_resp = await mc.get(f"/api/runs/{rid}/tasks")
    assert tasks_resp.status_code == 200 and len(tasks_resp.json()) == 1
    task_detail = await mc.get(f"/api/runs/{rid}/tasks/1")
    assert task_detail.status_code == 200 and task_detail.json()["name"] == "Install nginx"
    raw = await mc.get(f"/api/runs/{rid}/raw")
    assert raw.status_code == 200 and "PLAY RECAP" in raw.text
