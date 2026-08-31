import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.models import KbOccurrence, KbSignature, Run, Team


async def _make_team(db, name="kb-team", slug="kb-team"):
    t = Team(name=name, slug=slug)
    db.add(t)
    await db.flush()
    return t


async def test_kbsignature_defaults_and_insert(db):
    """A bare KbSignature inserts with the contract's server/python defaults."""
    sig = KbSignature(
        signature_key="ssh_connection_failed",
        title="SSH unreachable",
        representative_text="failed to connect to the host via ssh <ssh-banner>",
    )
    db.add(sig)
    await db.flush()
    await db.refresh(sig)
    assert isinstance(sig.id, uuid.UUID)
    assert sig.team_id is None                 # NULL = global tier
    assert sig.status == "needs-fix"           # server_default
    assert sig.match_patterns == {}            # JSONB '{}' default
    assert sig.links == []                     # JSONB '[]' default
    assert sig.category is None
    assert sig.created_at is not None
    assert sig.updated_at is not None


async def test_global_key_is_null_distinct_unique(db):
    """Exactly one global (team_id NULL) row per signature_key."""
    db.add(KbSignature(signature_key="dup_global", title="a", representative_text="x"))
    await db.flush()
    db.add(KbSignature(signature_key="dup_global", title="b", representative_text="y"))
    with pytest.raises(IntegrityError):
        await db.flush()
    await db.rollback()


async def test_team_key_unique_but_team_and_global_coexist(db):
    """One (team, key) row per team; a team row and a global row for the same key coexist."""
    team = await _make_team(db)
    # global + team rows for the same key are allowed (different uniqueness scopes)
    db.add(KbSignature(signature_key="shared_key", title="g", representative_text="g"))
    db.add(KbSignature(signature_key="shared_key", title="t",
                       representative_text="t", team_id=team.id))
    await db.flush()
    # a second row for the same (team, key) is rejected
    db.add(KbSignature(signature_key="shared_key", title="t2",
                       representative_text="t2", team_id=team.id))
    with pytest.raises(IntegrityError):
        await db.flush()
    await db.rollback()


async def test_kboccurrence_dedupe_unique(db):
    """uq_kb_occurrences_sig_run_seq rejects a duplicate (signature, run, task_seq)."""
    user_team = await _make_team(db, name="occ-team", slug="occ-team")
    sig = KbSignature(signature_key="occ_key", title="o",
                      representative_text="o", team_id=user_team.id)
    run = Run(status="failed", source="upload")
    db.add_all([sig, run])
    await db.flush()
    db.add(KbOccurrence(signature_id=sig.id, run_id=run.id, task_seq=3, host="hostA"))
    await db.flush()
    db.add(KbOccurrence(signature_id=sig.id, run_id=run.id, task_seq=3, host="hostB"))
    with pytest.raises(IntegrityError):
        await db.flush()
    await db.rollback()


async def test_signature_occurrences_cascade_delete(db):
    """Deleting a KbSignature cascades to its kb_occurrences (relationship + FK cascade)."""
    sig = KbSignature(signature_key="cascade_key", title="c", representative_text="c")
    run = Run(status="failed", source="upload")
    db.add_all([sig, run])
    await db.flush()
    db.add(KbOccurrence(signature_id=sig.id, run_id=run.id, task_seq=1))
    await db.flush()
    await db.delete(sig)
    await db.flush()
    remaining = (await db.scalars(
        select(KbOccurrence).where(KbOccurrence.run_id == run.id)
    )).all()
    assert remaining == []
