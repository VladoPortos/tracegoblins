import uuid

from app.core.crypto import encrypt_token
from app.models import AwxController, ControllerTeam, Project, Team, TeamMember
from app.services.visibility import is_project_visible


async def _setup(db, *, org_on_assignment=None, project_org=2):
    team = Team(name=f"t-{uuid.uuid4()}", slug=str(uuid.uuid4()))
    db.add(team); await db.flush()
    c = AwxController(name=f"c-{uuid.uuid4()}", base_url="https://awx.test",
                      auth_token_encrypted=encrypt_token("t"))
    db.add(c); await db.flush()
    db.add(ControllerTeam(controller_id=c.id, team_id=team.id,
                          awx_organization_id=org_on_assignment))
    p = Project(controller_id=c.id, awx_project_id=19, name="p", scm_type="git",
                organization_id=project_org)
    db.add(p); await db.flush()
    return team, c, p


async def test_member_of_assigned_team_sees_project(db, make_user):
    team, c, p = await _setup(db, org_on_assignment=None)
    user = await make_user(email=f"{uuid.uuid4()}@x.test", team=team)
    assert await is_project_visible(db, p, user) is True


async def test_non_member_does_not_see_project(db, make_user):
    team, c, p = await _setup(db)
    other = await make_user(email=f"{uuid.uuid4()}@x.test")  # General team, not `team`
    assert await is_project_visible(db, p, other) is False


async def test_org_scoped_assignment_excludes_other_org(db, make_user):
    # assignment scoped to org 99, project is org 2 → not visible
    team, c, p = await _setup(db, org_on_assignment=99, project_org=2)
    user = await make_user(email=f"{uuid.uuid4()}@x.test", team=team)
    assert await is_project_visible(db, p, user) is False


async def test_org_scoped_assignment_includes_matching_org(db, make_user):
    team, c, p = await _setup(db, org_on_assignment=2, project_org=2)
    user = await make_user(email=f"{uuid.uuid4()}@x.test", team=team)
    assert await is_project_visible(db, p, user) is True
