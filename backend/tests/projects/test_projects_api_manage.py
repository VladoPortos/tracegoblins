import uuid

from sqlalchemy import select

from app.core.crypto import encrypt_token
from app.models import AwxController, ControllerTeam, Project, Team


async def _project_for(db, team_id):
    c = AwxController(name=f"c-{uuid.uuid4()}", base_url="https://awx.test",
                      auth_token_encrypted=encrypt_token("t"))
    db.add(c); await db.flush()
    db.add(ControllerTeam(controller_id=c.id, team_id=team_id, awx_organization_id=None))
    p = Project(controller_id=c.id, awx_project_id=19, name="day2", scm_type="git",
                scm_url="https://git.test/day2.git", status="unlinked", organization_id=2)
    db.add(p); await db.flush()
    return c, p


async def _general(db):
    return await db.scalar(select(Team).where(Team.is_default.is_(True)))


async def test_put_git_writes_secret_writeonly(admin_client, db):
    gen = await _general(db)
    c, p = await _project_for(db, gen.id)
    r = await admin_client.put(f"/api/projects/{p.id}/git", json={
        "git_url_override": "https://override.test/d.git",
        "auth_type": "token", "secret": "supersecret",
    })
    assert r.status_code == 200
    body = r.json()
    assert body["has_git_secret"] is True
    assert "secret" not in body and "git_secret_encrypted" not in body
    assert body["status"] == "pending"
    await db.refresh(p)
    assert p.git_secret_encrypted is not None and p.git_secret_encrypted != "supersecret"

    # sentinel (omitted) leaves the secret intact; username change still applies
    r2 = await admin_client.put(f"/api/projects/{p.id}/git", json={
        "git_url_override": "https://override.test/d.git", "auth_type": "token",
    })
    assert r2.status_code == 200  # guard: a 422 here would leave the field non-None spuriously
    await db.refresh(p)
    assert p.git_secret_encrypted is not None  # unchanged

    # explicit empty clears it
    r3 = await admin_client.put(f"/api/projects/{p.id}/git", json={
        "git_url_override": "https://override.test/d.git", "auth_type": "none", "secret": "",
    })
    await db.refresh(p)
    assert p.git_secret_encrypted is None


async def test_put_git_rejects_non_https_override(admin_client, db):
    gen = await _general(db)
    c, p = await _project_for(db, gen.id)
    r = await admin_client.put(f"/api/projects/{p.id}/git", json={
        "git_url_override": "git@host:d.git", "auth_type": "none",
    })
    assert r.status_code == 422


async def test_put_git_requires_admin(authed_client, db):
    gen = await _general(db)
    c, p = await _project_for(db, gen.id)
    r = await authed_client.put(f"/api/projects/{p.id}/git", json={"auth_type": "none"})
    assert r.status_code == 403


async def test_clone_enqueues(admin_client, db, monkeypatch):
    gen = await _general(db)
    c, p = await _project_for(db, gen.id)

    # No-op the background worker so the enqueued task doesn't actually try to git-clone
    # the non-routable test URL (which would pollute and slow the run).
    import app.api.projects as papi
    async def _noop(_pid): return None
    monkeypatch.setattr(papi, "run_clone", _noop)

    r = await admin_client.post(f"/api/projects/{p.id}/clone")
    assert r.status_code == 202


async def test_refresh_mirror_nonmember_denied(admin_client, db):
    # Regression guard: admin role alone is NOT a path to refresh-mirror. The controller+project
    # are NOT assigned to any team the admin is in (deliberately no ControllerTeam row), so the
    # admin is denied. The denial is a 404 (not 403): the VisibleProject gate fires FIRST and an
    # unassigned controller's project is invisible to everyone (admin role grants no path) — a
    # strictly stronger denial that shadows the endpoint's defense-in-depth 403 team-check.
    c = AwxController(name=f"c-{uuid.uuid4()}", base_url="https://awx.test",
                      auth_token_encrypted=encrypt_token("t"))
    db.add(c); await db.flush()
    # deliberately NO ControllerTeam row
    p = Project(controller_id=c.id, awx_project_id=20, name="orphan", scm_type="git",
                scm_url="https://git.test/x.git", status="unlinked", organization_id=2)
    db.add(p); await db.flush()
    r = await admin_client.post(f"/api/projects/{p.id}/refresh-mirror")
    assert r.status_code == 404  # denied (admin-alone is not a path); 404 from the visibility gate
    assert r.status_code != 200  # the security invariant: must NOT succeed


async def test_refresh_mirror_member_allowed(authed_client, db, monkeypatch):
    gen = await _general(db)
    c, p = await _project_for(db, gen.id)

    async def _fake_sync(db_, controller, client):
        return 1

    import app.api.projects as papi
    monkeypatch.setattr(papi, "sync_projects", _fake_sync)

    class _FakeAwx:
        def __init__(self, *a, **k): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *e): return False
    monkeypatch.setattr(papi, "AwxClient", _FakeAwx)

    r = await authed_client.post(f"/api/projects/{p.id}/refresh-mirror")
    assert r.status_code == 200
