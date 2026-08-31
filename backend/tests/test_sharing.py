from __future__ import annotations

import uuid
from pathlib import Path

from sqlalchemy import func, select

from app.models import AuditLog, Run, RunShare, Team

ROOT = Path(__file__).resolve().parents[2]
UPLOADS = ROOT / "backend/tests/fixtures/logs"


async def _upload(client) -> str:
    text = (UPLOADS / "job_11140.txt").read_text(encoding="utf-8")
    r = await client.post("/api/runs", json={"text": text})
    assert r.status_code == 201
    return r.json()["id"]


async def test_share_with_user_then_list(authed_client, db, make_user):
    rid = await _upload(authed_client)
    target = await make_user(email="su1@example.com")
    r = await authed_client.post(f"/api/runs/{rid}/shares", json={"user_id": str(target.id)})
    assert r.status_code == 201
    body = r.json()
    assert body["run_id"] == rid and body["permission"] == "collaborate"
    assert body["user"]["id"] == str(target.id) and body["team"] is None
    lst = await authed_client.get(f"/api/runs/{rid}/shares")
    assert lst.status_code == 200 and len(lst.json()) == 1
    # audit row written
    n = await db.scalar(select(func.count()).select_from(AuditLog).where(AuditLog.action == "run_share"))
    assert n >= 1


async def test_share_with_team(authed_client, db):
    rid = await _upload(authed_client)
    team = Team(name="Owls", slug="owls")
    db.add(team)
    await db.flush()
    r = await authed_client.post(f"/api/runs/{rid}/shares", json={"team_id": str(team.id)})
    assert r.status_code == 201
    body = r.json()
    assert body["team"]["id"] == str(team.id) and body["team"]["slug"] == "owls"
    assert body["user"] is None


async def test_share_requires_exactly_one_target(authed_client, db, make_user):
    rid = await _upload(authed_client)
    target = await make_user(email="su2@example.com")
    team = Team(name="Hawks", slug="hawks")
    db.add(team)
    await db.flush()
    # both -> 422
    r1 = await authed_client.post(f"/api/runs/{rid}/shares",
                                  json={"user_id": str(target.id), "team_id": str(team.id)})
    assert r1.status_code == 422
    # neither -> 422
    r2 = await authed_client.post(f"/api/runs/{rid}/shares", json={})
    assert r2.status_code == 422


async def test_duplicate_share_409(authed_client, db, make_user):
    rid = await _upload(authed_client)
    target = await make_user(email="su3@example.com")
    a = await authed_client.post(f"/api/runs/{rid}/shares", json={"user_id": str(target.id)})
    assert a.status_code == 201
    b = await authed_client.post(f"/api/runs/{rid}/shares", json={"user_id": str(target.id)})
    assert b.status_code == 409


async def test_non_owner_cannot_share_or_list(authed_client, db, make_user, session_for):
    rid = await _upload(authed_client)
    owner_id = await db.scalar(select(Run.owner_user_id).where(Run.id == uuid.UUID(rid)))
    # snoop is not visible -> 404
    snoop = await make_user(email="snoopshare@example.com")
    sc = await session_for(snoop)
    assert (await sc.post(f"/api/runs/{rid}/shares", json={"user_id": str(owner_id)})).status_code == 404
    assert (await sc.get(f"/api/runs/{rid}/shares")).status_code == 404


async def test_shared_user_cannot_share_403(authed_client, db, make_user, session_for):
    rid = await _upload(authed_client)
    owner_id = await db.scalar(select(Run.owner_user_id).where(Run.id == uuid.UUID(rid)))
    target = await make_user(email="su4@example.com")
    db.add(RunShare(run_id=uuid.UUID(rid), shared_with_user_id=target.id, shared_by_user_id=owner_id))
    await db.flush()
    tc = await session_for(target)
    # visible (collaborator) but not owner -> 403 on share management
    assert (await tc.get(f"/api/runs/{rid}/shares")).status_code == 403
    other = uuid.uuid4()
    assert (await tc.post(f"/api/runs/{rid}/shares", json={"user_id": str(other)})).status_code == 403


async def test_unshare_revokes_access(authed_client, db, make_user, session_for):
    rid = await _upload(authed_client)
    target = await make_user(email="su5@example.com")
    created = await authed_client.post(f"/api/runs/{rid}/shares", json={"user_id": str(target.id)})
    share_id = created.json()["id"]
    tc = await session_for(target)
    assert (await tc.get(f"/api/runs/{rid}")).status_code == 200  # visible while shared
    # owner revokes — the shared client overwrote cookies, so look up the run's real owner
    # and re-login as them via session_for before the DELETE.
    from app.models import User
    owner_id = await db.scalar(select(Run.owner_user_id).where(Run.id == uuid.UUID(rid)))
    owner_user = await db.get(User, owner_id)
    oc = await session_for(owner_user)
    d = await oc.delete(f"/api/runs/{rid}/shares/{share_id}")
    assert d.status_code == 204
    # target loses access -> 404
    tc2 = await session_for(target)
    assert (await tc2.get(f"/api/runs/{rid}")).status_code == 404
    assert await db.scalar(
        select(func.count()).select_from(RunShare).where(RunShare.id == uuid.UUID(share_id))
    ) == 0


async def test_unshare_unknown_id_404(authed_client):
    rid = await _upload(authed_client)
    bogus = uuid.uuid4()
    assert (await authed_client.delete(f"/api/runs/{rid}/shares/{bogus}")).status_code == 404
