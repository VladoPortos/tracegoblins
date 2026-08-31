from __future__ import annotations

import uuid
from pathlib import Path

from sqlalchemy import select

from app.models import Run, RunShare, Team, TeamMember

ROOT = Path(__file__).resolve().parents[2]
UPLOADS = ROOT / "backend/tests/fixtures/logs"


async def _upload(client) -> str:
    text = (UPLOADS / "job_11140.txt").read_text(encoding="utf-8")
    r = await client.post("/api/runs", json={"text": text})
    assert r.status_code == 201
    return r.json()["id"]


async def test_direct_share_makes_run_readable(authed_client, db, make_user, session_for):
    rid = await _upload(authed_client)
    owner_id = await db.scalar(select(Run.owner_user_id).where(Run.id == uuid.UUID(rid)))
    target = await make_user(email="shareread@example.com")
    db.add(RunShare(run_id=uuid.UUID(rid), shared_with_user_id=target.id, shared_by_user_id=owner_id))
    await db.flush()
    tc = await session_for(target)
    assert (await tc.get(f"/api/runs/{rid}")).status_code == 200
    assert (await tc.get(f"/api/runs/{rid}/tasks")).status_code == 200
    assert (await tc.get(f"/api/runs/{rid}/tasks/1")).status_code == 200
    assert (await tc.get(f"/api/runs/{rid}/raw")).status_code == 200


async def test_team_owned_run_readable_by_member(authed_client, db, make_user, session_for):
    # owner uploads; we move the run onto a team; a co-member can read it.
    team = Team(name="Crew", slug="crew")
    db.add(team)
    await db.flush()
    member = await make_user(email="crewmate@example.com", team=team)
    rid = await _upload(authed_client)  # owner = member@ (General team), personal
    # move the run onto the team and add the owner to the team
    run = await db.get(Run, uuid.UUID(rid))
    run.team_id = team.id
    db.add(TeamMember(team_id=team.id, user_id=run.owner_user_id))
    await db.flush()
    mc = await session_for(member)
    assert (await mc.get(f"/api/runs/{rid}")).status_code == 200


async def test_private_run_still_404_for_non_collaborator(authed_client, make_user, session_for):
    rid = await _upload(authed_client)
    snoop = await make_user(email="snoop2@example.com")
    sc = await session_for(snoop)
    for path in (f"/api/runs/{rid}", f"/api/runs/{rid}/tasks",
                 f"/api/runs/{rid}/tasks/1", f"/api/runs/{rid}/raw"):
        assert (await sc.get(path)).status_code == 404


async def test_shared_user_cannot_delete_run_403(authed_client, db, make_user, session_for):
    rid = await _upload(authed_client)
    owner_id = await db.scalar(select(Run.owner_user_id).where(Run.id == uuid.UUID(rid)))
    target = await make_user(email="sharedeleter@example.com")
    db.add(RunShare(run_id=uuid.UUID(rid), shared_with_user_id=target.id, shared_by_user_id=owner_id))
    await db.flush()
    tc = await session_for(target)
    # visible (200 on GET) but not owner -> DELETE is 403, not 404
    assert (await tc.get(f"/api/runs/{rid}")).status_code == 200
    assert (await tc.delete(f"/api/runs/{rid}")).status_code == 403


async def test_non_visible_delete_still_404(authed_client, make_user, session_for):
    rid = await _upload(authed_client)
    snoop = await make_user(email="snoop3@example.com")
    sc = await session_for(snoop)
    assert (await sc.delete(f"/api/runs/{rid}")).status_code == 404
