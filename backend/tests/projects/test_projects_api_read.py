import uuid

from app.core.crypto import encrypt_token
from app.models import AwxController, ControllerTeam, Project, Run


async def _visible_project(db, user_team_id):
    c = AwxController(name=f"c-{uuid.uuid4()}", base_url="https://awx.test",
                      auth_token_encrypted=encrypt_token("t"))
    db.add(c); await db.flush()
    db.add(ControllerTeam(controller_id=c.id, team_id=user_team_id, awx_organization_id=None))
    p = Project(controller_id=c.id, awx_project_id=19, name="day2", scm_type="git",
                scm_url="https://git.test/day2.git", status="unlinked", organization_id=2)
    db.add(p); await db.flush()
    # two linked runs + one unrelated
    db.add(Run(source="awx", controller_id=c.id, project_id=19, status="ok",
               awx_job_id="100", awx_organization_id=2))
    db.add(Run(source="awx", controller_id=c.id, project_id=19, status="failed",
               awx_job_id="101", awx_organization_id=2))
    db.add(Run(source="awx", controller_id=c.id, project_id=77, status="ok",
               awx_job_id="102", awx_organization_id=2))
    await db.flush()
    return c, p


async def test_list_and_detail_visible(authed_client, db, make_user):
    # authed_client's user is "member@example.com" in the General team
    from sqlalchemy import select
    from app.models import Team
    gen = await db.scalar(select(Team).where(Team.is_default.is_(True)))
    c, p = await _visible_project(db, gen.id)

    r = await authed_client.get("/api/projects")
    assert r.status_code == 200
    body = r.json()
    ids = {it["id"] for it in body["items"]}
    assert str(p.id) in ids
    item = next(it for it in body["items"] if it["id"] == str(p.id))
    assert item["linked_run_count"] == 2

    d = await authed_client.get(f"/api/projects/{p.id}")
    assert d.status_code == 200
    detail = d.json()
    assert "git_secret_encrypted" not in detail and detail["has_git_secret"] is False
    assert detail["effective_git_url"] == "https://git.test/day2.git"

    runs = await authed_client.get(f"/api/projects/{p.id}/runs")
    assert runs.status_code == 200
    assert runs.json()["total"] == 2


async def test_detail_404_when_not_visible(authed_client, db):
    # project on a controller not assigned to the member's team
    c = AwxController(name=f"c-{uuid.uuid4()}", base_url="https://awx.test",
                      auth_token_encrypted=encrypt_token("t"))
    db.add(c); await db.flush()
    p = Project(controller_id=c.id, awx_project_id=5, name="hidden", scm_type="git")
    db.add(p); await db.flush()
    r = await authed_client.get(f"/api/projects/{p.id}")
    assert r.status_code == 404
