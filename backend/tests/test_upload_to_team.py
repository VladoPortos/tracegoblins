from __future__ import annotations

import uuid
from pathlib import Path

from sqlalchemy import select

from app.models import Run, Team, TeamMember

ROOT = Path(__file__).resolve().parents[2]
UPLOADS = ROOT / "backend/tests/fixtures/logs"


def _log() -> str:
    return (UPLOADS / "job_11140.txt").read_text(encoding="utf-8")


async def test_upload_to_team_member_ok(authed_client, db):
    # member@ (authed_client) is in General; make a team and add them.
    team = Team(name="Ravens", slug="ravens")
    db.add(team)
    await db.flush()
    # add member@ to the team
    from app.models import User
    me = await db.scalar(select(User).where(User.email == "member@example.com"))
    db.add(TeamMember(team_id=team.id, user_id=me.id))
    await db.flush()

    r = await authed_client.post("/api/runs", json={"text": _log(), "team_id": str(team.id)})
    assert r.status_code == 201
    rid = uuid.UUID(r.json()["id"])
    run = await db.get(Run, rid)
    assert run.team_id == team.id and run.source == "upload" and run.owner_user_id == me.id


async def test_upload_to_team_non_member_403(authed_client, db):
    team = Team(name="Lions", slug="lions")  # member@ is NOT in this team
    db.add(team)
    await db.flush()
    r = await authed_client.post("/api/runs", json={"text": _log(), "team_id": str(team.id)})
    assert r.status_code == 403


async def test_upload_to_unknown_team_403(authed_client):
    bogus = uuid.uuid4()
    r = await authed_client.post("/api/runs", json={"text": _log(), "team_id": str(bogus)})
    assert r.status_code == 403


async def test_upload_personal_unchanged(authed_client, db):
    r = await authed_client.post("/api/runs", json={"text": _log()})
    assert r.status_code == 201
    run = await db.get(Run, uuid.UUID(r.json()["id"]))
    assert run.team_id is None  # M2 behavior preserved


async def test_upload_to_team_multipart(authed_client, db):
    from app.models import User
    team = Team(name="Wolves", slug="wolves")
    db.add(team)
    await db.flush()
    me = await db.scalar(select(User).where(User.email == "member@example.com"))
    db.add(TeamMember(team_id=team.id, user_id=me.id))
    await db.flush()
    files = {"file": ("job.txt", _log().encode("utf-8"), "text/plain")}
    r = await authed_client.post("/api/runs", files=files, data={"team_id": str(team.id)})
    assert r.status_code == 201
    run = await db.get(Run, uuid.UUID(r.json()["id"]))
    assert run.team_id == team.id


async def test_invalid_team_id_422(authed_client):
    r = await authed_client.post("/api/runs", json={"text": _log(), "team_id": "not-a-uuid"})
    assert r.status_code == 422
