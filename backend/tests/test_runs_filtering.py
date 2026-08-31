from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from urllib.parse import quote

from app.models import AwxController, ControllerTeam, Run, Team


async def _awx_controller(db, *, name=None):
    c = AwxController(
        name=name or f"ctrl-{uuid.uuid4().hex[:8]}", base_url="https://awx.example",
        auth_token_encrypted="gAAAAAFake==",  # stored value; not decrypted in these tests
    )
    db.add(c)
    await db.flush()
    return c


async def _awx_run(db, controller, *, owner, org_id, org_name, template, awx_user,
                   status_, launch_type, when):
    r = Run(
        source="awx", owner_user_id=owner.id, team_id=None,
        controller_id=controller.id, awx_job_id=str(uuid.uuid4().int % 10_000_000),
        awx_user=awx_user, template_name=template, status=status_,
        awx_organization_id=org_id, awx_organization_name=org_name,
        awx_launch_type=launch_type, log_time=when,
    )
    db.add(r)
    await db.flush()
    return r


async def test_runs_filters_scoped_to_visibility(client, db, make_user, session_for):
    # member of a team the controller is assigned to (all-orgs) sees AWX runs
    team = Team(name="FilterTeam", slug=f"ft-{uuid.uuid4().hex[:6]}")
    db.add(team)
    await db.flush()
    member = await make_user(email=f"f-{uuid.uuid4().hex[:6]}@example.com", team=team)
    ctrl = await _awx_controller(db)
    db.add(ControllerTeam(controller_id=ctrl.id, team_id=team.id))  # all orgs
    await db.flush()

    now = datetime.now(timezone.utc)
    await _awx_run(db, ctrl, owner=member, org_id=2, org_name="DXC",
                   template="Day2Actions", awx_user="cloudauto", status_="failed",
                   launch_type="manual", when=now - timedelta(days=1))
    await _awx_run(db, ctrl, owner=member, org_id=3, org_name="Other",
                   template="Provision", awx_user="bob", status_="successful",
                   launch_type="scheduled", when=now - timedelta(days=10))
    await db.flush()

    mc = await session_for(member)

    # organization filter
    r = await mc.get("/api/runs?scope=team&organization=2")
    assert r.status_code == 200 and r.json()["total"] == 1
    assert r.json()["items"][0]["template_name"] == "Day2Actions"

    # status CSV multi
    r = await mc.get("/api/runs?scope=team&status=failed,unreachable")
    assert r.json()["total"] == 1

    # template trgm substring (case-insensitive ILIKE)
    r = await mc.get("/api/runs?scope=team&template=day2")
    assert r.json()["total"] == 1

    # awx_user substring
    r = await mc.get("/api/runs?scope=team&awx_user=cloud")
    assert r.json()["total"] == 1

    # launch_type exact
    r = await mc.get("/api/runs?scope=team&launch_type=scheduled")
    assert r.json()["total"] == 1

    # controller filter
    r = await mc.get(f"/api/runs?scope=team&controller={ctrl.id}")
    assert r.json()["total"] == 2

    # time range narrows to the recent one (URL-encode the + in the timezone offset)
    after = quote((now - timedelta(days=3)).isoformat())
    r = await mc.get(f"/api/runs?scope=team&launched_after={after}")
    assert r.json()["total"] == 1

    # search over template OR user
    r = await mc.get("/api/runs?scope=team&search=bob")
    assert r.json()["total"] == 1

    # pagination + total
    r = await mc.get("/api/runs?scope=team&limit=1&offset=0")
    body = r.json()
    assert body["total"] == 2 and len(body["items"]) == 1


async def test_runs_filter_not_visible_excluded(client, db, make_user, session_for):
    # a different user, not in any assigned team, sees nothing even with a matching filter
    team = Team(name="OwnerTeam2", slug=f"ot2-{uuid.uuid4().hex[:6]}")
    db.add(team)
    await db.flush()
    owner = await make_user(email=f"ow-{uuid.uuid4().hex[:6]}@example.com", team=team)
    ctrl = await _awx_controller(db)
    db.add(ControllerTeam(controller_id=ctrl.id, team_id=team.id))
    await db.flush()
    now = datetime.now(timezone.utc)
    await _awx_run(db, ctrl, owner=owner, org_id=2, org_name="DXC",
                   template="Day2Actions", awx_user="cloudauto", status_="failed",
                   launch_type="manual", when=now)
    await db.flush()

    outsider = await make_user(email=f"os-{uuid.uuid4().hex[:6]}@example.com")
    oc = await session_for(outsider)
    r = await oc.get("/api/runs?scope=team&organization=2")
    assert r.json()["total"] == 0


def _recap(host):
    return [{"host": host, "ok": 1, "changed": 0, "unreachable": 0,
             "failed": 0, "skipped": 0, "rescued": 0, "ignored": 0}]


async def test_search_is_server_side_across_fields(client, db, make_user, session_for):
    """Regression (F1): the search box is applied SERVER-side across template / awx_user / job_id /
    org / workflow / recap host, so a match on ANY page is found and `total` reflects the matches.
    (Previously search only filtered the first loaded page client-side -> false 'no matches'.)"""
    user = await make_user(email=f"srch-{uuid.uuid4().hex[:6]}@example.com")
    now = datetime.now(timezone.utc)

    def _run(**kw):
        base = dict(source="upload", owner_user_id=user.id, team_id=None,
                    status="successful", log_time=now, recap=[])
        base.update(kw)
        db.add(Run(**base))

    _run(template_name="Deploy Web", awx_user="alice", awx_job_id="9001", recap=_recap("web01.prod"))
    _run(template_name="Patch DB", awx_user="bob", awx_job_id="9002", recap=_recap("db07.staging"))
    _run(template_name="Cleanup", awx_user="carol", awx_job_id="9003",
         awx_organization_name="Platform", awx_workflow_name="NightlyFlow")
    await db.flush()

    uc = await session_for(user)

    async def _search(term):
        r = await uc.get(f"/api/runs?scope=mine&search={quote(term)}")
        assert r.status_code == 200
        body = r.json()
        return body["total"], {it["template_name"] for it in body["items"]}

    assert await _search("Deploy") == (1, {"Deploy Web"})        # template_name
    assert await _search("bob") == (1, {"Patch DB"})             # awx_user
    assert await _search("9003") == (1, {"Cleanup"})             # awx_job_id (job_id)
    assert await _search("web01") == (1, {"Deploy Web"})         # recap host (JSONB)
    assert await _search("db07.staging") == (1, {"Patch DB"})    # recap host
    assert await _search("Platform") == (1, {"Cleanup"})         # awx_organization_name
    assert await _search("NightlyFlow") == (1, {"Cleanup"})      # awx_workflow_name
    # genuine no-match is a true server zero (exercises the full or_, incl. team subquery + host)
    assert await _search("zzz-nonexistent-zzz") == (0, set())
