from __future__ import annotations

import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
UPLOADS = ROOT / "backend/tests/fixtures/logs"


async def _upload(client) -> str:
    text = (UPLOADS / "job_11140.txt").read_text(encoding="utf-8")
    r = await client.post("/api/runs", json={"text": text})
    assert r.status_code == 201
    return r.json()["id"]


async def test_mentionable_lists_owner_and_team_members(authed_client, db, make_user, session_for):
    from app.models import Run, Team
    t = Team(name=f"TM-{uuid.uuid4().hex[:8]}", slug=f"tm-{uuid.uuid4().hex[:8]}")
    db.add(t)
    await db.flush()
    owner = await make_user(email="owner-men@example.com", display_name="Olivia Owner", team=t)
    await make_user(email="mate-men@example.com", display_name="Tara Teammate", team=t)
    # make_user(team=t) already adds TeamMember rows; no extra db.add needed
    await db.flush()
    oc = await session_for(owner)
    rid = (await oc.post("/api/runs", json={"text": (UPLOADS / "job_11140.txt").read_text()})).json()["id"]
    run = await db.get(Run, uuid.UUID(rid))
    run.team_id = t.id
    await db.flush()
    # all team members (owner + teammate) are mentionable
    r = await oc.get(f"/api/runs/{rid}/mentionable")
    assert r.status_code == 200
    names = {u["display_name"] for u in r.json()}
    assert {"Olivia Owner", "Tara Teammate"} <= names


async def test_mentionable_filters_by_q(authed_client, db, make_user, session_for):
    from app.models import Run, Team
    t = Team(name=f"TQ-{uuid.uuid4().hex[:8]}", slug=f"tq-{uuid.uuid4().hex[:8]}")
    db.add(t)
    await db.flush()
    owner = await make_user(email="owner-q@example.com", display_name="Zed Zephyr", team=t)
    await make_user(email="mate-q@example.com", display_name="Quinn Query", team=t)
    # make_user(team=t) already adds TeamMember rows; no extra db.add needed
    await db.flush()
    oc = await session_for(owner)
    rid = (await oc.post("/api/runs", json={"text": (UPLOADS / "job_11140.txt").read_text()})).json()["id"]
    run = await db.get(Run, uuid.UUID(rid))
    run.team_id = t.id
    await db.flush()
    r = await oc.get(f"/api/runs/{rid}/mentionable?q=quin")
    names = [u["display_name"] for u in r.json()]
    assert names == ["Quinn Query"]


async def test_mentionable_404_for_non_visible_user(authed_client, make_user, session_for):
    rid = await _upload(authed_client)
    snoop = await make_user(email="snoop-men@example.com")
    sc = await session_for(snoop)
    assert (await sc.get(f"/api/runs/{rid}/mentionable")).status_code == 404


async def test_mentionable_excludes_non_visible_outsiders(authed_client, make_user, session_for):
    rid = await _upload(authed_client)  # personal run owned by member@example.com
    await make_user(email="outsider-men@example.com", display_name="Nope Person")
    # owner queries: outsider (different team, no share) must NOT appear
    r = await authed_client.get(f"/api/runs/{rid}/mentionable")
    assert r.status_code == 200
    assert all(u["email"] != "outsider-men@example.com" for u in r.json())
