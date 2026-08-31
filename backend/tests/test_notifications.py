from __future__ import annotations

import uuid
from pathlib import Path

from sqlalchemy import func, select

from app.models import Comment, Notification, Run, RunShare, Task, Team, TeamMember, User
from app.services.notifications import (
    create_mention_notifications,
    create_share_notifications,
)

ROOT = Path(__file__).resolve().parents[2]
UPLOADS = ROOT / "backend/tests/fixtures/logs"


async def _upload(client) -> str:
    text = (UPLOADS / "job_11140.txt").read_text(encoding="utf-8")
    r = await client.post("/api/runs", json={"text": text})
    assert r.status_code == 201
    return r.json()["id"]


async def _make_run(db, owner) -> Run:
    run = Run(owner_user_id=owner.id, source="upload", status="successful")
    db.add(run)
    await db.flush()
    return run


async def test_create_share_notifications_user_target(db, make_user):
    owner = await make_user(email="owner-c1@example.com")
    target = await make_user(email="target-c1@example.com")
    run = await _make_run(db, owner)
    share = RunShare(run_id=run.id, shared_with_user_id=target.id,
                     shared_by_user_id=owner.id)
    db.add(share)
    await db.flush()

    await create_share_notifications(db, run=run, share=share, actor_id=owner.id)
    await db.flush()

    rows = (await db.execute(
        select(Notification).where(Notification.type == "share")
    )).scalars().all()
    assert len(rows) == 1
    n = rows[0]
    assert n.user_id == target.id
    assert n.run_id == run.id
    assert n.actor_user_id == owner.id
    assert n.comment_id is None
    assert n.read_at is None


async def test_create_share_notifications_team_fans_out_excluding_sharer(db, make_user):
    owner = await make_user(email="owner-c1t@example.com")
    team = Team(name="C1 Team", slug="c1-team")
    db.add(team)
    await db.flush()
    m1 = await make_user(email="m1-c1t@example.com", team=team)
    m2 = await make_user(email="m2-c1t@example.com", team=team)
    # owner is ALSO a member of the team — must be excluded from the fan-out.
    db.add(TeamMember(team_id=team.id, user_id=owner.id))
    await db.flush()
    run = await _make_run(db, owner)
    share = RunShare(run_id=run.id, shared_with_team_id=team.id,
                     shared_by_user_id=owner.id)
    db.add(share)
    await db.flush()

    await create_share_notifications(db, run=run, share=share, actor_id=owner.id)
    await db.flush()

    recipients = {
        n.user_id for n in (await db.execute(
            select(Notification).where(Notification.type == "share")
        )).scalars().all()
    }
    assert recipients == {m1.id, m2.id}  # owner/sharer excluded, no dups


async def test_create_share_notifications_self_user_target_is_noop(db, make_user):
    owner = await make_user(email="self-c1@example.com")
    run = await _make_run(db, owner)
    # pathological: sharing to yourself — no self-notification.
    share = RunShare(run_id=run.id, shared_with_user_id=owner.id,
                     shared_by_user_id=owner.id)
    db.add(share)
    await db.flush()

    await create_share_notifications(db, run=run, share=share, actor_id=owner.id)
    await db.flush()

    assert await db.scalar(
        select(func.count()).select_from(Notification)
    ) == 0


async def test_create_mention_notifications_excludes_author_and_dedups(db, make_user):
    from app.models import Comment
    author = await make_user(email="author-c2@example.com")
    a = await make_user(email="ment-a-c2@example.com")
    b = await make_user(email="ment-b-c2@example.com")
    run = await _make_run(db, author)
    comment = Comment(run_id=run.id, task_seq=1, author_user_id=author.id,
                      body="hi @a @b", mentions=[a.id, b.id])
    db.add(comment)
    await db.flush()

    # include the author and a duplicate of `a` — both must collapse away.
    await create_mention_notifications(
        db, comment=comment, mention_ids=[a.id, b.id, author.id, a.id],
        actor_id=author.id,
    )
    await db.flush()

    rows = (await db.execute(
        select(Notification).where(Notification.type == "mention")
    )).scalars().all()
    recipients = sorted(str(n.user_id) for n in rows)
    assert recipients == sorted([str(a.id), str(b.id)])
    for n in rows:
        assert n.run_id == run.id
        assert n.comment_id == comment.id
        assert n.actor_user_id == author.id
        assert n.read_at is None


async def test_share_endpoint_creates_share_notification_for_user(
    authed_client, client, db, make_user, session_for
):
    rid = await _upload(authed_client)  # owner = member@example.com
    target = await make_user(email="share-notif-target@example.com")
    r = await authed_client.post(
        f"/api/runs/{rid}/shares", json={"user_id": str(target.id)}
    )
    assert r.status_code == 201
    rows = (await db.execute(
        select(Notification).where(
            Notification.type == "share",
            Notification.user_id == target.id,
        )
    )).scalars().all()
    assert len(rows) == 1
    assert str(rows[0].run_id) == rid


async def test_share_endpoint_team_fans_out_excluding_sharer(
    authed_client, client, db, make_user, session_for
):
    rid = await _upload(authed_client)  # owner = member@example.com
    team = Team(name="C3 Team", slug="c3-team")
    db.add(team)
    await db.flush()
    tm1 = await make_user(email="c3-tm1@example.com", team=team)
    tm2 = await make_user(email="c3-tm2@example.com", team=team)
    # add the owner (member@example.com) to the team too — they must NOT be notified.
    owner = await db.scalar(select(Run.owner_user_id).where(Run.id == uuid.UUID(rid)))
    db.add(TeamMember(team_id=team.id, user_id=owner))
    await db.flush()

    r = await authed_client.post(
        f"/api/runs/{rid}/shares", json={"team_id": str(team.id)}
    )
    assert r.status_code == 201
    recipients = {
        n.user_id for n in (await db.execute(
            select(Notification).where(Notification.type == "share")
        )).scalars().all()
    }
    assert recipients == {tm1.id, tm2.id}  # owner/sharer excluded


async def test_comment_creates_mention_notification(
    authed_client, client, db, make_user, session_for
):
    rid = await _upload(authed_client)  # owner/author = member@example.com
    # B is a direct-share recipient so B is run-visible and mentionable.
    b = await make_user(email="c4-b@example.com")
    sr = await authed_client.post(
        f"/api/runs/{rid}/shares", json={"user_id": str(b.id)}
    )
    assert sr.status_code == 201
    owner_id = await db.scalar(select(Run.owner_user_id).where(Run.id == uuid.UUID(rid)))

    # owner comments mentioning B (visible) AND themselves (must be dropped from notify).
    r = await authed_client.post(
        f"/api/runs/{rid}/tasks/1/comments",
        json={"body": "ping @c4-b @member", "mentions": [str(b.id), str(owner_id)]},
    )
    assert r.status_code == 201
    cid = r.json()["id"]

    rows = (await db.execute(
        select(Notification).where(Notification.type == "mention")
    )).scalars().all()
    assert len(rows) == 1
    n = rows[0]
    assert n.user_id == b.id              # only the visible, non-author mention
    assert str(n.comment_id) == cid
    assert str(n.run_id) == rid


async def test_comment_dropped_mention_creates_no_notification(
    authed_client, client, db, make_user, session_for
):
    rid = await _upload(authed_client)  # owner/author = member@example.com
    stranger = await make_user(email="c4-stranger@example.com")  # NOT run-visible
    r = await authed_client.post(
        f"/api/runs/{rid}/tasks/1/comments",
        json={"body": "hi @stranger", "mentions": [str(stranger.id)]},
    )
    assert r.status_code == 201
    # the stranger is not run-visible -> mention dropped -> no notification, no leak.
    assert await db.scalar(
        select(func.count()).select_from(Notification).where(
            Notification.user_id == stranger.id
        )
    ) == 0


async def test_comment_edit_notifies_only_newly_added_mentions(
    authed_client, client, db, make_user, session_for
):
    rid = await _upload(authed_client)  # author = member@example.com
    b = await make_user(email="c5-b@example.com")
    c = await make_user(email="c5-c@example.com")
    for u in (b, c):
        sr = await authed_client.post(
            f"/api/runs/{rid}/shares", json={"user_id": str(u.id)}
        )
        assert sr.status_code == 201

    # initial comment mentions only B -> 1 notification.
    r = await authed_client.post(
        f"/api/runs/{rid}/tasks/1/comments",
        json={"body": "hi @c5-b", "mentions": [str(b.id)]},
    )
    assert r.status_code == 201
    cid = r.json()["id"]
    assert await db.scalar(
        select(func.count()).select_from(Notification).where(
            Notification.type == "mention"
        )
    ) == 1

    # edit to mention B AND C -> only C is newly added -> exactly 1 NEW notification.
    pr = await authed_client.patch(
        f"/api/comments/{cid}",
        json={"body": "hi @c5-b @c5-c", "mentions": [str(b.id), str(c.id)]},
    )
    assert pr.status_code == 200

    total = await db.scalar(
        select(func.count()).select_from(Notification).where(
            Notification.type == "mention"
        )
    )
    assert total == 2  # B's original + C's new; B is NOT re-notified
    c_count = await db.scalar(
        select(func.count()).select_from(Notification).where(
            Notification.type == "mention", Notification.user_id == c.id
        )
    )
    b_count = await db.scalar(
        select(func.count()).select_from(Notification).where(
            Notification.type == "mention", Notification.user_id == b.id
        )
    )
    assert c_count == 1 and b_count == 1


# ---------------------------------------------------------------------------
# C6 — notification_to_out query mapper (denormalized display)
# ---------------------------------------------------------------------------

async def test_notification_to_out_denormalizes_display(db, make_user):
    from app.api.collab_schemas import NotificationOut
    from app.services.collab_query import notification_to_out

    actor = await make_user(email="c6-actor@example.com")
    recipient = await make_user(email="c6-recip@example.com")
    run = await _make_run(db, actor)
    run.template_name = "Deploy Web"
    db.add(Task(run_id=run.id, seq=1, play_name="play", name="Install nginx",
                status="failed", hosts={}, items_count=0))
    comment = Comment(run_id=run.id, task_seq=1, author_user_id=actor.id, body="x",
                      mentions=[recipient.id])
    db.add(comment)
    await db.flush()
    notif = Notification(user_id=recipient.id, type="mention", run_id=run.id,
                         comment_id=comment.id, actor_user_id=actor.id)
    db.add(notif)
    await db.flush()

    out = notification_to_out(
        notif,
        actor_names={actor.id: actor.display_name},
        run_templates={run.id: run.template_name},
        comment_info={comment.id: (comment.run_id, comment.task_seq)},
        task_names={(run.id, 1): "Install nginx"},
    )
    assert isinstance(out, NotificationOut)
    assert out.type == "mention"
    assert out.run_id == str(run.id)
    assert out.run_template == "Deploy Web"
    assert out.task_seq == 1
    assert out.task_name == "Install nginx"
    assert out.actor_name == actor.display_name
    assert out.read_at is None


async def test_notification_to_out_handles_deleted_run_gracefully(db, make_user):
    from app.services.collab_query import notification_to_out

    actor = await make_user(email="c6-del-actor@example.com")
    recipient = await make_user(email="c6-del-recip@example.com")
    # run_id/comment_id NULLed by SET NULL after a run delete.
    notif = Notification(user_id=recipient.id, type="mention", run_id=None,
                         comment_id=None, actor_user_id=actor.id)
    db.add(notif)
    await db.flush()

    out = notification_to_out(
        notif,
        actor_names={actor.id: actor.display_name},
        run_templates={},
        comment_info={},
        task_names={},
    )
    assert out.run_id is None
    assert out.run_template is None
    assert out.task_seq is None
    assert out.task_name is None
    assert out.actor_name == actor.display_name


# ---------------------------------------------------------------------------
# C7 — GET /api/notifications + GET /api/notifications/unread_count
# ---------------------------------------------------------------------------

async def test_list_notifications_and_unread_count(
    authed_client, client, db, make_user, session_for
):
    from datetime import datetime, timezone

    # member@example.com (authed_client) is the recipient.
    recipient = await db.scalar(
        select(User).where(User.email == "member@example.com")
    )
    actor = await make_user(email="c7-actor@example.com")
    run = await _make_run(db, actor)
    run.template_name = "Nightly Backup"
    await db.flush()
    # two notifications for the recipient (one read, one unread).
    n_read = Notification(user_id=recipient.id, type="mention", run_id=run.id,
                          actor_user_id=actor.id,
                          read_at=datetime.now(timezone.utc))
    n_unread = Notification(user_id=recipient.id, type="share", run_id=run.id,
                            actor_user_id=actor.id)
    db.add(n_read)
    db.add(n_unread)
    # a notification for ANOTHER user — must never appear for the recipient.
    other = await make_user(email="c7-other@example.com")
    db.add(Notification(user_id=other.id, type="share", run_id=run.id,
                        actor_user_id=actor.id))
    await db.flush()

    lst = await authed_client.get("/api/notifications")
    assert lst.status_code == 200
    body = lst.json()
    assert len(body["items"]) == 2     # only the recipient's two
    assert all(i["run_template"] == "Nightly Backup" for i in body["items"])

    unread_only = await authed_client.get("/api/notifications?unread_only=true")
    assert unread_only.status_code == 200
    assert len(unread_only.json()["items"]) == 1
    assert unread_only.json()["items"][0]["type"] == "share"

    cnt = await authed_client.get("/api/notifications/unread_count")
    assert cnt.status_code == 200
    assert cnt.json() == {"count": 1}


# ---------------------------------------------------------------------------
# C8 — POST /api/notifications/read (mark by ids or all; cross-user no-op)
# ---------------------------------------------------------------------------

async def test_mark_read_by_ids_and_all(
    authed_client, client, db, make_user, session_for
):
    recipient = await db.scalar(
        select(User).where(User.email == "member@example.com")
    )
    actor = await make_user(email="c8-actor@example.com")
    run = await _make_run(db, actor)
    n1 = Notification(user_id=recipient.id, type="mention", run_id=run.id,
                      actor_user_id=actor.id)
    n2 = Notification(user_id=recipient.id, type="share", run_id=run.id,
                      actor_user_id=actor.id)
    n3 = Notification(user_id=recipient.id, type="mention", run_id=run.id,
                      actor_user_id=actor.id)
    # a notification owned by SOMEONE ELSE — marking its id must be a no-op.
    other = await make_user(email="c8-other@example.com")
    n_other = Notification(user_id=other.id, type="share", run_id=run.id,
                           actor_user_id=actor.id)
    for n in (n1, n2, n3, n_other):
        db.add(n)
    await db.flush()
    n1_id, n_other_id = str(n1.id), str(n_other.id)

    # mark n1 + the foreign id by ids -> only n1 marked; foreign untouched; count 2.
    r = await authed_client.post(
        "/api/notifications/read", json={"ids": [n1_id, n_other_id]}
    )
    assert r.status_code == 200
    assert r.json() == {"count": 2}     # n2, n3 still unread
    await db.refresh(n1)
    await db.refresh(n_other)
    assert n1.read_at is not None
    assert n_other.read_at is None      # foreign row untouched (no-op)

    # mark all -> recipient's remaining unread cleared; count 0.
    r2 = await authed_client.post("/api/notifications/read", json={"all": True})
    assert r2.status_code == 200
    assert r2.json() == {"count": 0}
    await db.refresh(n_other)
    assert n_other.read_at is None      # still untouched — "all" is caller-scoped


async def test_mark_read_requires_ids_or_all(authed_client):
    r = await authed_client.post("/api/notifications/read", json={})
    assert r.status_code == 422


# ---------------------------------------------------------------------------
# C9 — SET-NULL lifecycle: deleting a run leaves a graceful notification
# ---------------------------------------------------------------------------

async def test_run_delete_set_nulls_notifications(
    authed_client, client, db, make_user, session_for
):
    rid = await _upload(authed_client)  # owner = member@example.com
    b = await make_user(email="c9-b@example.com")
    sr = await authed_client.post(
        f"/api/runs/{rid}/shares", json={"user_id": str(b.id)}
    )
    assert sr.status_code == 201
    # B comments mentioning the owner -> a mention notification linked to run+comment.
    bc = await session_for(b)
    cr = await bc.post(
        f"/api/runs/{rid}/tasks/1/comments",
        json={"body": "look @member", "mentions": [
            str(await db.scalar(select(Run.owner_user_id).where(Run.id == uuid.UUID(rid))))
        ]},
    )
    assert cr.status_code == 201
    notif = await db.scalar(
        select(Notification).where(Notification.type == "mention")
    )
    assert notif is not None and str(notif.run_id) == rid
    assert notif.comment_id is not None

    # owner deletes the run (switch back to the owner's session).
    oc = await session_for(
        await db.scalar(select(User).where(User.email == "member@example.com"))
    )
    dr = await oc.delete(f"/api/runs/{rid}")
    assert dr.status_code == 204

    # the notification row survives with SET NULL'd refs (inbox never dangles).
    await db.refresh(notif)
    assert notif.run_id is None
    assert notif.comment_id is None
    assert notif.actor_user_id == b.id   # actor (a user) is NOT deleted -> still set

    # and it lists gracefully via the API for the owner.
    lst = await oc.get("/api/notifications")
    assert lst.status_code == 200
    item = next(i for i in lst.json()["items"] if i["id"] == str(notif.id))
    assert item["run_id"] is None
    assert item["run_template"] is None
    assert item["task_name"] is None
    assert item["actor_name"] == b.display_name
