from __future__ import annotations

import pytest
from sqlalchemy import func, select

from app.kb.service import match_run
from app.models import KbOccurrence, KbSignature, Run, Task, Team, TeamMember, User
from app.security.passwords import hash_password
from tests.kb._blobs import SSH_BLOB_A, SSH_BLOB_B

pytestmark = pytest.mark.asyncio


async def _team(db, name="Ops-MR", slug="ops-mr"):
    t = Team(name=name, slug=slug)
    db.add(t)
    await db.flush()
    return t


async def _user(db, team, email="mr@example.com"):
    u = User(email=email, password_hash=hash_password("hunter2hunter2"),
             display_name="mr", is_active=True)
    db.add(u)
    await db.flush()
    db.add(TeamMember(team_id=team.id, user_id=u.id))
    await db.flush()
    return u


async def _ssh_sig(db, team_id):
    s = KbSignature(
        team_id=team_id, signature_key="ssh_connection_failed", title="SSH down",
        category="connectivity", status="known-issue",
        representative_text="failed to connect to the host via ssh",
    )
    db.add(s)
    await db.flush()
    return s


async def _run_with_two_ssh_tasks(db, *, owner, team_id):
    run = Run(source="upload", owner_user_id=owner.id, team_id=team_id, status="failed")
    db.add(run)
    await db.flush()
    db.add(Task(run_id=run.id, seq=1, play_name="p", name="Connect hostA",
                status="unreachable", hosts={"hostA": "unreachable"}, error=SSH_BLOB_A))
    db.add(Task(run_id=run.id, seq=2, play_name="p", name="Connect hostB",
                status="unreachable", hosts={"hostB": "unreachable"}, error=SSH_BLOB_B))
    # a passing task with no error -> must be ignored
    db.add(Task(run_id=run.id, seq=3, play_name="p", name="OK task",
                status="ok", hosts={"hostA": "ok"}, error=None))
    await db.flush()
    return run


async def test_match_run_records_two_occurrences_on_one_signature(db):
    t = await _team(db)
    u = await _user(db, t)
    sig = await _ssh_sig(db, t.id)
    run = await _run_with_two_ssh_tasks(db, owner=u, team_id=t.id)

    n = await match_run(db, run)
    assert n == 2  # both SSH tasks matched the same signature

    occ = (await db.execute(
        select(KbOccurrence).where(KbOccurrence.signature_id == sig.id).order_by(KbOccurrence.task_seq)
    )).scalars().all()
    assert [o.task_seq for o in occ] == [1, 2]
    assert {o.run_id for o in occ} == {run.id}
    assert occ[0].host == "hostA" and occ[1].host == "hostB"


async def test_match_run_is_idempotent(db):
    t = await _team(db, "Ops-Idem", "ops-idem")
    u = await _user(db, t, email="idem@example.com")
    sig = await _ssh_sig(db, t.id)
    run = await _run_with_two_ssh_tasks(db, owner=u, team_id=t.id)

    await match_run(db, run)
    # second call: the unique constraint (signature_id, run_id, task_seq) dedupes -> no dupes, no error
    n2 = await match_run(db, run)
    total = await db.scalar(
        select(func.count()).select_from(KbOccurrence).where(KbOccurrence.signature_id == sig.id)
    )
    assert total == 2
    assert n2 == 0  # nothing new upserted on the re-run


async def test_match_run_ignores_unmatched_and_passing_tasks(db):
    t = await _team(db, "Ops-None", "ops-none")
    u = await _user(db, t, email="none@example.com")
    # No signature exists -> nothing matches.
    run = await _run_with_two_ssh_tasks(db, owner=u, team_id=t.id)
    n = await match_run(db, run)
    assert n == 0
    total = await db.scalar(select(func.count()).select_from(KbOccurrence))
    assert total == 0


async def test_match_run_new_plus_dup_mix_keeps_new_occurrences(db):
    # Regression for the bare-rollback bug: a re-match where SOME tasks already have an
    # occurrence (dup) and SOME are new must keep the new ones. A bare `await db.rollback()`
    # on the first dup would tear down the whole session txn and silently lose the new rows;
    # the per-occurrence SAVEPOINT (begin_nested) scopes the undo to just the dup.
    t = await _team(db, "Ops-Mix", "ops-mix")
    u = await _user(db, t, email="mix@example.com")
    sig = await _ssh_sig(db, t.id)

    # First match: ONLY seq=1 exists -> one occurrence recorded.
    run = Run(source="upload", owner_user_id=u.id, team_id=t.id, status="failed")
    db.add(run)
    await db.flush()
    db.add(Task(run_id=run.id, seq=1, play_name="p", name="Connect hostA",
                status="unreachable", hosts={"hostA": "unreachable"}, error=SSH_BLOB_A))
    await db.flush()
    assert await match_run(db, run) == 1

    # Now add a NEW failed task seq=2 and re-match: seq=1 is a dup (SAVEPOINT-skipped),
    # seq=2 is new and MUST survive. Both occurrences present at the end.
    db.add(Task(run_id=run.id, seq=2, play_name="p", name="Connect hostB",
                status="unreachable", hosts={"hostB": "unreachable"}, error=SSH_BLOB_B))
    await db.flush()
    n2 = await match_run(db, run)
    assert n2 == 1  # only the new seq=2 was upserted (seq=1 was the SAVEPOINT-skipped dup)

    occ = (await db.execute(
        select(KbOccurrence).where(KbOccurrence.signature_id == sig.id).order_by(KbOccurrence.task_seq)
    )).scalars().all()
    assert [o.task_seq for o in occ] == [1, 2]  # BOTH survive — seq=2 was NOT lost
