from __future__ import annotations

import pytest
from sqlalchemy import func, select

from app.kb.service import backfill_signature
from app.models import (
    KbOccurrence, KbSignature, Run, Task, Team, TeamMember, User,
)
from app.security.passwords import hash_password
from tests.kb._blobs import SSH_BLOB_A, SSH_BLOB_B

pytestmark = pytest.mark.asyncio


async def _team(db, name, slug):
    t = Team(name=name, slug=slug)
    db.add(t)
    await db.flush()
    return t


async def _user(db, team, email):
    u = User(email=email, password_hash=hash_password("hunter2hunter2"),
             display_name=email.split("@")[0], is_active=True)
    db.add(u)
    await db.flush()
    db.add(TeamMember(team_id=team.id, user_id=u.id))
    await db.flush()
    return u


async def _failed_run(db, *, owner, team_id, error):
    run = Run(source="upload", owner_user_id=owner.id, team_id=team_id, status="unreachable")
    db.add(run)
    await db.flush()
    db.add(Task(run_id=run.id, seq=1, play_name="p", name="Connect",
                status="unreachable", hosts={"h": "unreachable"}, error=error))
    await db.flush()
    return run


async def test_backfill_team_signature_finds_existing_team_run(db):
    t = await _team(db, "BF", "bf")
    u = await _user(db, t, "bf@example.com")
    # A pre-existing failed team-owned run (no occurrence yet).
    run = await _failed_run(db, owner=u, team_id=t.id, error=SSH_BLOB_A)

    sig = KbSignature(team_id=t.id, signature_key="ssh_connection_failed", title="SSH",
                      category="connectivity", status="known-issue",
                      representative_text="failed to connect to the host via ssh")
    db.add(sig)
    await db.flush()

    n = await backfill_signature(db, sig)
    assert n == 1
    occ = await db.scalar(
        select(func.count()).select_from(KbOccurrence)
        .where(KbOccurrence.signature_id == sig.id, KbOccurrence.run_id == run.id)
    )
    assert occ == 1


async def test_backfill_team_signature_finds_member_personal_upload(db):
    t = await _team(db, "BF2", "bf2")
    u = await _user(db, t, "bf2@example.com")
    # A member's PERSONAL upload (team_id None) whose audience includes team t.
    run = await _failed_run(db, owner=u, team_id=None, error=SSH_BLOB_A)

    sig = KbSignature(team_id=t.id, signature_key="ssh_connection_failed", title="SSH",
                      category="connectivity", status="known-issue",
                      representative_text="failed to connect to the host via ssh")
    db.add(sig)
    await db.flush()

    n = await backfill_signature(db, sig)
    assert n == 1
    occ = await db.scalar(
        select(func.count()).select_from(KbOccurrence)
        .where(KbOccurrence.signature_id == sig.id, KbOccurrence.run_id == run.id)
    )
    assert occ == 1


async def test_backfill_global_signature_scans_all_runs(db):
    t1 = await _team(db, "G1", "g1")
    t2 = await _team(db, "G2", "g2")
    u1 = await _user(db, t1, "g1@example.com")
    u2 = await _user(db, t2, "g2@example.com")
    run1 = await _failed_run(db, owner=u1, team_id=t1.id, error=SSH_BLOB_A)
    run2 = await _failed_run(db, owner=u2, team_id=t2.id, error=SSH_BLOB_B)

    gsig = KbSignature(team_id=None, signature_key="ssh_connection_failed", title="SSH global",
                       category="connectivity", status="known-issue",
                       representative_text="failed to connect to the host via ssh")
    db.add(gsig)
    await db.flush()

    n = await backfill_signature(db, gsig)
    assert n == 2  # both teams' runs matched the global signature
    runs = {run1.id, run2.id}
    found = set((await db.execute(
        select(KbOccurrence.run_id).where(KbOccurrence.signature_id == gsig.id)
    )).scalars().all())
    assert found == runs


async def test_backfill_is_idempotent(db):
    t = await _team(db, "BFI", "bfi")
    u = await _user(db, t, "bfi@example.com")
    await _failed_run(db, owner=u, team_id=t.id, error=SSH_BLOB_A)
    sig = KbSignature(team_id=t.id, signature_key="ssh_connection_failed", title="SSH",
                      category="connectivity", status="known-issue",
                      representative_text="failed to connect to the host via ssh")
    db.add(sig)
    await db.flush()

    await backfill_signature(db, sig)
    n2 = await backfill_signature(db, sig)
    assert n2 == 0
    total = await db.scalar(
        select(func.count()).select_from(KbOccurrence).where(KbOccurrence.signature_id == sig.id)
    )
    assert total == 1
