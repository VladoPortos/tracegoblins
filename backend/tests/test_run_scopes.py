from __future__ import annotations

import uuid
from pathlib import Path

from sqlalchemy import select

from app.models import Run, RunShare, Team, TeamMember, User

ROOT = Path(__file__).resolve().parents[2]
UPLOADS = ROOT / "backend/tests/fixtures/logs"


async def _upload(client, team_id: str | None = None) -> str:
    text = (UPLOADS / "job_11140.txt").read_text(encoding="utf-8")
    payload: dict = {"text": text}
    if team_id:
        payload["team_id"] = team_id
    r = await client.post("/api/runs", json=payload)
    assert r.status_code == 201
    return r.json()["id"]


async def test_scope_mine_only_personal(authed_client, db):
    me = await db.scalar(select(User).where(User.email == "member@example.com"))
    team = Team(name="Bears", slug="bears")
    db.add(team)
    await db.flush()
    db.add(TeamMember(team_id=team.id, user_id=me.id))
    await db.flush()
    personal = await _upload(authed_client)
    team_run = await _upload(authed_client, team_id=str(team.id))
    r = await authed_client.get("/api/runs?scope=mine")
    ids = {it["id"] for it in r.json()["items"]}
    assert personal in ids and team_run not in ids  # mine excludes team uploads
    assert r.json()["total"] == 1


async def test_default_scope_is_mine(authed_client):
    rid = await _upload(authed_client)
    r = await authed_client.get("/api/runs")  # no scope -> mine (back-compat)
    assert r.status_code == 200
    assert any(it["id"] == rid for it in r.json()["items"])


async def test_scope_shared_lists_direct_shares(authed_client, db, make_user, session_for):
    rid = await _upload(authed_client)
    owner_id = await db.scalar(select(Run.owner_user_id).where(Run.id == uuid.UUID(rid)))
    target = await make_user(email="scopeshare@example.com")
    db.add(RunShare(run_id=uuid.UUID(rid), shared_with_user_id=target.id, shared_by_user_id=owner_id))
    await db.flush()
    tc = await session_for(target)
    r = await tc.get("/api/runs?scope=shared")
    ids = {it["id"] for it in r.json()["items"]}
    assert rid in ids
    # target's own personal upload should NOT appear in shared
    own = await _upload(tc)
    r2 = await tc.get("/api/runs?scope=shared")
    ids2 = {it["id"] for it in r2.json()["items"]}
    assert rid in ids2 and own not in ids2


async def test_scope_team_includes_team_owned_and_team_shared(authed_client, db, make_user, session_for):
    # owner uploads to team T (team-owned) and shares a personal run to T (team-shared).
    team = Team(name="Foxes", slug="foxes")
    db.add(team)
    await db.flush()
    me = await db.scalar(select(User).where(User.email == "member@example.com"))
    db.add(TeamMember(team_id=team.id, user_id=me.id))
    await db.flush()
    member = await make_user(email="teamscope@example.com", team=team)
    team_owned = await _upload(authed_client, team_id=str(team.id))
    personal = await _upload(authed_client)
    owner_id = await db.scalar(select(Run.owner_user_id).where(Run.id == uuid.UUID(personal)))
    db.add(RunShare(run_id=uuid.UUID(personal), shared_with_team_id=team.id, shared_by_user_id=owner_id))
    await db.flush()
    mc = await session_for(member)
    r = await mc.get("/api/runs?scope=team")
    items = {it["id"]: it for it in r.json()["items"]}
    assert team_owned in items and personal in items
    # team cards carry team identity for grouping
    assert items[team_owned]["team_id"] == str(team.id)
    assert items[team_owned]["team_name"] == "Foxes"


async def test_scope_team_excludes_own_personal(authed_client, db):
    me = await db.scalar(select(User).where(User.email == "member@example.com"))
    team = Team(name="Hares", slug="hares")
    db.add(team)
    await db.flush()
    db.add(TeamMember(team_id=team.id, user_id=me.id))
    await db.flush()
    personal = await _upload(authed_client)  # team_id null
    r = await authed_client.get("/api/runs?scope=team")
    ids = {it["id"] for it in r.json()["items"]}
    assert personal not in ids


async def test_runcard_team_fields_null_for_personal(authed_client):
    rid = await _upload(authed_client)
    r = await authed_client.get("/api/runs?scope=mine")
    card = next(it for it in r.json()["items"] if it["id"] == rid)
    assert card["team_id"] is None and card["team_name"] is None


async def test_run_detail_exposes_owner_user_id(authed_client, db):
    rid = await _upload(authed_client)
    me = await db.scalar(select(User).where(User.email == "member@example.com"))
    r = await authed_client.get(f"/api/runs/{rid}")
    assert r.status_code == 200
    body = r.json()
    assert body["owner_user_id"] == str(me.id)  # backend emits it for the D5 owner gate
