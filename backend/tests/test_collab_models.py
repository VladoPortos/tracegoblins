
import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.models import (
    Annotation, Comment, Notification, Run, RunShare, Team, User,
)


async def _user(db, email="m1@example.com"):
    u = User(email=email, password_hash="x", display_name=email.split("@")[0])
    db.add(u)
    await db.flush()
    return u


async def _team(db, name="Alpha", slug="alpha"):
    t = Team(name=name, slug=slug)
    db.add(t)
    await db.flush()
    return t


async def _run(db, owner, team_id=None):
    run = Run(source="upload", owner_user_id=owner.id, team_id=team_id, status="ok",
              host_count=0, task_count=0, warnings_count=0, recap=[])
    db.add(run)
    await db.flush()
    return run


async def test_run_share_user_roundtrip_and_defaults(db):
    owner = await _user(db, "owner1@example.com")
    target = await _user(db, "t1@example.com")
    run = await _run(db, owner)
    share = RunShare(run_id=run.id, shared_with_user_id=target.id, shared_by_user_id=owner.id)
    db.add(share)
    await db.flush()
    got = await db.scalar(select(RunShare).where(RunShare.id == share.id))
    assert got.permission == "collaborate"        # column default
    assert got.shared_with_team_id is None
    assert got.created_at is not None


async def test_run_share_team_roundtrip(db):
    owner = await _user(db, "owner2@example.com")
    team = await _team(db, "Beta", "beta")
    run = await _run(db, owner)
    share = RunShare(run_id=run.id, shared_with_team_id=team.id, shared_by_user_id=owner.id)
    db.add(share)
    await db.flush()
    got = await db.scalar(select(RunShare).where(RunShare.id == share.id))
    assert got.shared_with_user_id is None and got.shared_with_team_id == team.id


async def test_run_share_xor_check_rejects_both_targets(db):
    owner = await _user(db, "owner3@example.com")
    target = await _user(db, "t3@example.com")
    team = await _team(db, "Gamma", "gamma")
    run = await _run(db, owner)
    with pytest.raises(IntegrityError):  # ck_run_shares_exactly_one_target
        async with db.begin_nested():
            db.add(RunShare(run_id=run.id, shared_with_user_id=target.id,
                            shared_with_team_id=team.id, shared_by_user_id=owner.id))
            await db.flush()


async def test_run_share_xor_check_rejects_no_target(db):
    owner = await _user(db, "owner4@example.com")
    run = await _run(db, owner)
    with pytest.raises(IntegrityError):  # ck_run_shares_exactly_one_target
        async with db.begin_nested():
            db.add(RunShare(run_id=run.id, shared_by_user_id=owner.id))
            await db.flush()


async def test_run_share_dup_user_rejected(db):
    owner = await _user(db, "owner5@example.com")
    target = await _user(db, "t5@example.com")
    run = await _run(db, owner)
    db.add(RunShare(run_id=run.id, shared_with_user_id=target.id, shared_by_user_id=owner.id))
    await db.flush()
    with pytest.raises(IntegrityError):  # uq_run_shares_user partial-unique
        async with db.begin_nested():
            db.add(RunShare(run_id=run.id, shared_with_user_id=target.id, shared_by_user_id=owner.id))
            await db.flush()


async def test_annotation_defaults_and_roundtrip(db):
    owner = await _user(db, "owner6@example.com")
    run = await _run(db, owner)
    ann = Annotation(run_id=run.id, task_seq=1, author_user_id=owner.id, note="boom",
                     tags=["needs-fix"], links=[{"label": "doc", "url": "https://x"}])
    db.add(ann)
    await db.flush()
    got = await db.scalar(select(Annotation).where(Annotation.id == ann.id))
    assert got.note == "boom" and got.tags == ["needs-fix"]
    assert got.links == [{"label": "doc", "url": "https://x"}]
    assert got.resolved is False and got.created_at is not None


async def test_comment_thread_and_mentions(db):
    owner = await _user(db, "owner7@example.com")
    mentioned = await _user(db, "men7@example.com")
    run = await _run(db, owner)
    parent = Comment(run_id=run.id, task_seq=1, author_user_id=owner.id, body="hi",
                     mentions=[mentioned.id])
    db.add(parent)
    await db.flush()
    reply = Comment(run_id=run.id, task_seq=1, author_user_id=mentioned.id, body="re",
                    parent_id=parent.id)
    db.add(reply)
    await db.flush()
    got = await db.scalar(select(Comment).where(Comment.id == parent.id))
    assert got.mentions == [mentioned.id] and got.deleted_at is None and got.edited_at is None
    got_reply = await db.scalar(select(Comment).where(Comment.id == reply.id))
    assert got_reply.parent_id == parent.id


async def test_comment_cascades_on_run_delete(db):
    from sqlalchemy import func
    owner = await _user(db, "owner8@example.com")
    run = await _run(db, owner)
    db.add(Comment(run_id=run.id, task_seq=1, author_user_id=owner.id, body="x"))
    db.add(Annotation(run_id=run.id, task_seq=1, author_user_id=owner.id, note="y"))
    db.add(RunShare(run_id=run.id, shared_with_user_id=owner.id, shared_by_user_id=owner.id))
    await db.flush()
    await db.delete(run)
    await db.flush()
    rid = run.id
    assert await db.scalar(select(func.count()).select_from(Comment).where(Comment.run_id == rid)) == 0
    assert await db.scalar(select(func.count()).select_from(Annotation).where(Annotation.run_id == rid)) == 0
    assert await db.scalar(select(func.count()).select_from(RunShare).where(RunShare.run_id == rid)) == 0


async def test_notification_set_null_on_run_delete(db):
    owner = await _user(db, "owner9@example.com")
    recipient = await _user(db, "rec9@example.com")
    run = await _run(db, owner)
    notif = Notification(user_id=recipient.id, type="share", run_id=run.id,
                         actor_user_id=owner.id)
    db.add(notif)
    await db.flush()
    nid = notif.id
    rid = recipient.id
    await db.delete(run)
    await db.flush()
    # populate_existing=True forces SQLAlchemy to overwrite the cached identity-map instance
    # with the freshly-fetched DB row (run_id SET NULL by the FK cascade).
    got = await db.scalar(
        select(Notification).where(Notification.id == nid)
        .execution_options(populate_existing=True)
    )
    assert got is not None and got.run_id is None  # SET NULL, inbox never dangles
    assert got.user_id == rid


async def test_notification_defaults(db):
    recipient = await _user(db, "rec10@example.com")
    notif = Notification(user_id=recipient.id, type="mention")
    db.add(notif)
    await db.flush()
    got = await db.scalar(select(Notification).where(Notification.id == notif.id))
    assert got.read_at is None and got.created_at is not None
    assert got.run_id is None and got.comment_id is None and got.actor_user_id is None


async def test_team_delete_set_nulls_run_team_id(db):
    """runs.team_id FK is ON DELETE SET NULL: deleting a team nulls its runs'
    team_id (and the run survives) — team-scoped listing/visibility never
    references a deleted team."""
    from sqlalchemy import func
    owner = await _user(db, "owner-teamfk@example.com")
    team = await _team(db, "Doomed", "doomed")
    run = await _run(db, owner, team_id=team.id)
    rid = run.id
    await db.delete(team)
    await db.flush()
    db.expire_all()
    got = await db.scalar(select(Run).where(Run.id == rid))
    assert got is not None and got.team_id is None  # SET NULL, run survives
    # listing/count of the team's runs no longer references the deleted team
    assert await db.scalar(
        select(func.count()).select_from(Run).where(Run.team_id == team.id)
    ) == 0
