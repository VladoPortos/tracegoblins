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


async def _comment(client, rid, **kw) -> dict:
    r = await client.post(f"/api/runs/{rid}/tasks/1/comments", json=kw)
    assert r.status_code == 201, r.text
    return r.json()


async def test_author_edits_comment_sets_edited_at(authed_client):
    rid = await _upload(authed_client)
    c = await _comment(authed_client, rid, body="orig")
    r = await authed_client.patch(f"/api/comments/{c['id']}", json={"body": "edited"})
    assert r.status_code == 200
    out = r.json()
    assert out["body"] == "edited" and out["edited_at"] is not None


async def test_author_soft_deletes_returns_tombstone(authed_client):
    rid = await _upload(authed_client)
    c = await _comment(authed_client, rid, body="bye")
    r = await authed_client.delete(f"/api/comments/{c['id']}")
    assert r.status_code == 200  # 200 + tombstone, NOT 204
    out = r.json()
    assert out["body"] is None and out["deleted_at"] is not None
    # the tombstone still appears in the thread with body null
    thread = (await authed_client.get(f"/api/runs/{rid}/tasks/1/comments")).json()
    assert len(thread) == 1 and thread[0]["body"] is None and thread[0]["deleted_at"] is not None


async def test_non_visible_user_gets_404_on_comment_patch_delete(authed_client, make_user, session_for):
    rid = await _upload(authed_client)
    c = await _comment(authed_client, rid, body="x")
    snoop = await make_user(email="snoop-cmod@example.com")
    sc = await session_for(snoop)
    assert (await sc.patch(f"/api/comments/{c['id']}", json={"body": "h"})).status_code == 404
    assert (await sc.delete(f"/api/comments/{c['id']}")).status_code == 404


async def test_visible_non_author_cannot_patch_but_owner_can_delete(authed_client, db, make_user, session_for):
    from app.models import Run, Team
    t = Team(name=f"TC-{uuid.uuid4().hex[:8]}", slug=f"tc-{uuid.uuid4().hex[:8]}")
    db.add(t)
    await db.flush()
    # make_user(team=t) adds the user to team t; no second TeamMember insert needed.
    owner = await make_user(email="owner-cmod@example.com", team=t)
    collab = await make_user(email="collab-cmod@example.com", team=t)  # noqa: F841
    await db.flush()
    oc = await session_for(owner)
    rid = (await oc.post("/api/runs", json={"text": (UPLOADS / "job_11140.txt").read_text()})).json()["id"]
    run = await db.get(Run, uuid.UUID(rid))
    run.team_id = t.id
    await db.flush()
    cid = (await oc.post(f"/api/runs/{rid}/tasks/1/comments", json={"body": "owned"})).json()["id"]
    cc = await session_for(collab)
    # visible collaborator, not the author -> PATCH 403
    assert (await cc.patch(f"/api/comments/{cid}", json={"body": "hax"})).status_code == 403
    # owner moderates (soft-delete) -> 200 tombstone (re-attach owner: cookie-overwrite)
    oc2 = await session_for(owner)
    r = await oc2.delete(f"/api/comments/{cid}")
    assert r.status_code == 200 and r.json()["deleted_at"] is not None


async def test_malformed_cid_is_422_not_500(authed_client):
    # FastAPI resolves `cid: uuid.UUID` via path param — malformed UUID -> 422 automatically.
    r = await authed_client.patch("/api/comments/not-a-uuid", json={"body": "x"})
    assert r.status_code == 422
    r2 = await authed_client.delete("/api/comments/not-a-uuid")
    assert r2.status_code == 422


async def test_patch_re_resolves_mentions_drops_non_visible(authed_client, db, make_user):
    rid = await _upload(authed_client)
    me = (await authed_client.get("/api/auth/me")).json()
    outsider = await make_user(email="outsider-patch@example.com")
    c = await _comment(authed_client, rid, body="orig", mentions=[me["id"]])
    # PATCH with outsider in mentions -> outsider dropped, only visible (self) survives
    r = await authed_client.patch(
        f"/api/comments/{c['id']}",
        json={"body": "updated", "mentions": [me["id"], str(outsider.id)]},
    )
    assert r.status_code == 200
    out = r.json()
    assert out["body"] == "updated"
    assert out["mentions"] == [me["id"]]  # outsider dropped


async def test_delete_of_deleted_comment_returns_tombstone(authed_client):
    # Soft-deleting an already-deleted comment is idempotent (sets deleted_at again).
    rid = await _upload(authed_client)
    c = await _comment(authed_client, rid, body="once")
    r1 = await authed_client.delete(f"/api/comments/{c['id']}")
    assert r1.status_code == 200
    r2 = await authed_client.delete(f"/api/comments/{c['id']}")
    assert r2.status_code == 200 and r2.json()["deleted_at"] is not None
