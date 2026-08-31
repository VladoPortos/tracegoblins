from __future__ import annotations

import pytest

from app.kb.service import run_audience_team_ids
from app.models import (
    AwxController, ControllerTeam, Run, Team, TeamMember, User,
)
from app.security.passwords import hash_password

pytestmark = pytest.mark.asyncio


async def _team(db, name, slug):
    t = Team(name=name, slug=slug)
    db.add(t)
    await db.flush()
    return t


async def _user(db, email, *, team):
    u = User(email=email, password_hash=hash_password("hunter2hunter2"),
             display_name=email.split("@")[0], is_active=True)
    db.add(u)
    await db.flush()
    db.add(TeamMember(team_id=team.id, user_id=u.id))
    await db.flush()
    return u


async def test_team_owned_upload_audience(db):
    t = await _team(db, "Ops", "ops")
    u = await _user(db, "ops1@example.com", team=t)
    run = Run(source="upload", owner_user_id=u.id, team_id=t.id, status="failed")
    db.add(run)
    await db.flush()
    assert await run_audience_team_ids(db, run) == {t.id}


async def test_personal_upload_audience_is_uploader_teams(db):
    t1 = await _team(db, "Alpha", "alpha")
    t2 = await _team(db, "Beta", "beta")
    u = await _user(db, "multi@example.com", team=t1)
    db.add(TeamMember(team_id=t2.id, user_id=u.id))  # also a member of Beta
    await db.flush()
    run = Run(source="upload", owner_user_id=u.id, team_id=None, status="failed")
    db.add(run)
    await db.flush()
    assert await run_audience_team_ids(db, run) == {t1.id, t2.id}


async def test_awx_run_audience_via_controller_teams(db):
    t = await _team(db, "Net", "net")
    other = await _team(db, "Sec", "sec")
    ctrl = AwxController(name="ctrl-aud", base_url="https://awx.example",
                         auth_token_encrypted="x")
    db.add(ctrl)
    await db.flush()
    # all-orgs link for team Net; an org-specific link for team Sec on a DIFFERENT org.
    db.add(ControllerTeam(controller_id=ctrl.id, team_id=t.id, awx_organization_id=None))
    db.add(ControllerTeam(controller_id=ctrl.id, team_id=other.id, awx_organization_id=99))
    await db.flush()
    run = Run(source="awx", controller_id=ctrl.id, awx_organization_id=2,
              awx_job_id="555", status="failed")
    db.add(run)
    await db.flush()
    # Net's all-orgs link applies; Sec's org=99 link does NOT (run is org=2).
    assert await run_audience_team_ids(db, run) == {t.id}


async def test_awx_run_audience_org_specific_match(db):
    t = await _team(db, "Net2", "net2")
    ctrl = AwxController(name="ctrl-aud2", base_url="https://awx.example",
                         auth_token_encrypted="x")
    db.add(ctrl)
    await db.flush()
    db.add(ControllerTeam(controller_id=ctrl.id, team_id=t.id, awx_organization_id=7))
    await db.flush()
    run = Run(source="awx", controller_id=ctrl.id, awx_organization_id=7,
              awx_job_id="556", status="failed")
    db.add(run)
    await db.flush()
    assert await run_audience_team_ids(db, run) == {t.id}
