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


async def _annotate(client, rid, **kw) -> str:
    r = await client.post(f"/api/runs/{rid}/tasks/1/annotations", json=kw)
    assert r.status_code == 201, r.text
    return r.json()["id"]


async def test_author_can_patch_own_annotation(authed_client):
    rid = await _upload(authed_client)
    aid = await _annotate(authed_client, rid, note="first", tags=[])
    r = await authed_client.patch(f"/api/annotations/{aid}",
                                  json={"note": "edited", "resolved": True, "tags": ["resolved"]})
    assert r.status_code == 200
    a = r.json()
    assert a["note"] == "edited" and a["resolved"] is True and a["tags"] == ["resolved"]


async def test_patch_rejects_unknown_tag_and_bad_link(authed_client):
    rid = await _upload(authed_client)
    aid = await _annotate(authed_client, rid, note="x", tags=[])
    assert (await authed_client.patch(f"/api/annotations/{aid}",
                                      json={"tags": ["nope"]})).status_code == 422
    assert (await authed_client.patch(
        f"/api/annotations/{aid}",
        json={"links": [{"label": "x", "url": "javascript:alert(1)"}]})).status_code == 422


async def test_author_can_delete_own_annotation(authed_client):
    rid = await _upload(authed_client)
    aid = await _annotate(authed_client, rid, note="x")
    assert (await authed_client.delete(f"/api/annotations/{aid}")).status_code == 204
    lst = await authed_client.get(f"/api/runs/{rid}/annotations")
    assert lst.json() == []


async def test_non_visible_user_gets_404_on_patch_and_delete(authed_client, make_user, session_for):
    rid = await _upload(authed_client)
    aid = await _annotate(authed_client, rid, note="x")
    snoop = await make_user(email="snoop-mod@example.com")
    sc = await session_for(snoop)
    assert (await sc.patch(f"/api/annotations/{aid}", json={"note": "h"})).status_code == 404
    assert (await sc.delete(f"/api/annotations/{aid}")).status_code == 404


async def test_malformed_uuid_aid_returns_422(authed_client):
    """Malformed UUID in path → 422, not 500."""
    r = await authed_client.patch("/api/annotations/not-a-uuid", json={"note": "x"})
    assert r.status_code == 422
    r2 = await authed_client.delete("/api/annotations/not-a-uuid")
    assert r2.status_code == 422


async def test_visible_non_author_collaborator_cannot_patch_but_owner_can_delete(
    authed_client, db, make_user, session_for
):
    from app.models import Run, Team

    # Create a fresh team so both owner and collab are members
    t = Team(name=f"T-{uuid.uuid4().hex[:8]}", slug=f"t-{uuid.uuid4().hex[:8]}")
    db.add(t)
    await db.flush()
    owner = await make_user(email="owner-mod@example.com", team=t)
    collab = await make_user(email="collab-mod@example.com", team=t)
    # make_user already adds to `team=t`; owner also added to t via make_user
    await db.flush()

    # Switch to owner, upload a run
    oc = await session_for(owner)
    up = await oc.post("/api/runs", json={"text": (UPLOADS / "job_11140.txt").read_text()})
    assert up.status_code == 201
    rid = up.json()["id"]

    # Set run.team_id so it's team-owned and visible to collab
    run = await db.get(Run, uuid.UUID(rid))
    run.team_id = t.id
    await db.flush()

    # Owner creates annotation
    aid = (await oc.post(f"/api/runs/{rid}/tasks/1/annotations",
                         json={"note": "owned"})).json()["id"]

    # collab B: visible (team-owned) but NOT the author -> PATCH 403
    cc = await session_for(collab)
    assert (await cc.patch(f"/api/annotations/{aid}", json={"note": "hax"})).status_code == 403

    # owner can moderate (delete) the annotation
    oc2 = await session_for(owner)
    assert (await oc2.delete(f"/api/annotations/{aid}")).status_code == 204
