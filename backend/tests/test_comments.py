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


async def test_post_and_get_comment_thread(authed_client):
    rid = await _upload(authed_client)
    r = await authed_client.post(f"/api/runs/{rid}/tasks/1/comments", json={"body": "first"})
    assert r.status_code == 201
    c = r.json()
    assert c["body"] == "first" and c["task_seq"] == 1 and c["parent_id"] is None
    assert c["author_name"] == "member" and c["deleted_at"] is None and c["edited_at"] is None
    # reply (single level)
    r2 = await authed_client.post(f"/api/runs/{rid}/tasks/1/comments",
                                  json={"body": "reply", "parent_id": c["id"]})
    assert r2.status_code == 201 and r2.json()["parent_id"] == c["id"]
    thread = (await authed_client.get(f"/api/runs/{rid}/tasks/1/comments")).json()
    assert [t["body"] for t in thread] == ["first", "reply"]


async def test_mentions_keep_only_run_visible_users(authed_client, db, make_user, session_for):
    rid = await _upload(authed_client)
    # capture owner-side values before any session_for switch overwrites the jar
    # A non-visible outsider id must be dropped; a self-mention id is persisted (resolution
    # is visibility-only; self-exclusion for NOTIFICATIONS is Phase C, not here).
    me = (await authed_client.get("/api/auth/me")).json()
    my_id = me["id"]
    outsider = await make_user(email="outsider-c@example.com")  # in General, NOT visible to this run
    outsider_id = str(outsider.id)
    body = {"body": "hey @me @ghost", "mentions": [my_id, outsider_id, str(uuid.uuid4())]}
    # re-attach owner because make_user/session usage above may have touched the jar
    r = await authed_client.post(f"/api/runs/{rid}/tasks/1/comments", json=body)
    assert r.status_code == 201
    c = r.json()
    # only the visible (owner) id survives; outsider + random uuid dropped silently
    assert c["mentions"] == [my_id]
    assert c["body"] == "hey @me @ghost"  # body stored verbatim


async def test_non_visible_user_gets_404_on_thread_and_post(authed_client, make_user, session_for):
    rid = await _upload(authed_client)
    snoop = await make_user(email="snoop-c@example.com")
    sc = await session_for(snoop)
    assert (await sc.get(f"/api/runs/{rid}/tasks/1/comments")).status_code == 404
    assert (await sc.post(f"/api/runs/{rid}/tasks/1/comments",
                          json={"body": "x"})).status_code == 404


async def test_mention_creates_notification_for_mentioned_not_author(authed_client, db, make_user, session_for):
    """Phase C (C4) wiring: a mention creates a notification for the mentioned user,
    NOT for the author. A self-mention (author mentions themselves) produces no row."""
    from app.models import Notification
    from sqlalchemy import select
    rid = await _upload(authed_client)
    me = (await authed_client.get("/api/auth/me")).json()
    # Share the run with B so B is run-visible and mentionable.
    b = await make_user(email="c4-comments-b@example.com")
    await authed_client.post(f"/api/runs/{rid}/shares", json={"user_id": str(b.id)})
    # Author mentions B (visible) and themselves (self-mention → no notification).
    await authed_client.post(
        f"/api/runs/{rid}/tasks/1/comments",
        json={"body": "hi @b @me", "mentions": [str(b.id), me["id"]]},
    )
    # Exactly one notification: for B (not the author; not a self-mention).
    rows = (await db.execute(
        select(Notification).where(Notification.type == "mention")
    )).scalars().all()
    assert len(rows) == 1
    assert rows[0].user_id == b.id


async def test_reply_parent_from_another_run_is_422(authed_client):
    # A parent comment that belongs to a DIFFERENT run must not graft a cross-run thread.
    rid_a = await _upload(authed_client)
    rid_b = await _upload(authed_client)
    parent = await authed_client.post(f"/api/runs/{rid_a}/tasks/1/comments", json={"body": "on A"})
    assert parent.status_code == 201
    foreign_parent_id = parent.json()["id"]
    r = await authed_client.post(
        f"/api/runs/{rid_b}/tasks/1/comments",
        json={"body": "reply on B", "parent_id": foreign_parent_id},
    )
    assert r.status_code == 422  # cross-run parent rejected — not 201, not 500


async def test_reply_parent_from_other_task_is_422(authed_client):
    # A parent on the same run but a DIFFERENT task is rejected (single-level, same-task).
    rid = await _upload(authed_client)
    parent = await authed_client.post(f"/api/runs/{rid}/tasks/1/comments", json={"body": "task1"})
    pid = parent.json()["id"]
    r = await authed_client.post(
        f"/api/runs/{rid}/tasks/2/comments", json={"body": "x", "parent_id": pid}
    )
    assert r.status_code == 422


async def test_non_uuid_parent_or_annotation_id_is_422_not_500(authed_client):
    rid = await _upload(authed_client)
    r1 = await authed_client.post(
        f"/api/runs/{rid}/tasks/1/comments", json={"body": "x", "parent_id": "not-a-uuid"}
    )
    assert r1.status_code == 422
    r2 = await authed_client.post(
        f"/api/runs/{rid}/tasks/1/comments", json={"body": "x", "annotation_id": "nope"}
    )
    assert r2.status_code == 422


async def test_annotation_id_from_another_run_is_422(authed_client):
    rid_a = await _upload(authed_client)
    rid_b = await _upload(authed_client)
    ann = await authed_client.post(f"/api/runs/{rid_a}/tasks/1/annotations", json={"note": "on A"})
    foreign_ann_id = ann.json()["id"]
    r = await authed_client.post(
        f"/api/runs/{rid_b}/tasks/1/comments",
        json={"body": "x", "annotation_id": foreign_ann_id},
    )
    assert r.status_code == 422
