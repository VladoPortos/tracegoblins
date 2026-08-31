"""Fix B — KB drawer returns real pg_trgm similarity for fuzzy matches (not 0.0).

Cases:
  1. Fuzzy match: different signature_key but similar representative_text -> score in (0, 1).
  2. Exact match: same signature_key -> score == 1.0 (regression guard).
"""
from __future__ import annotations

import json

import pytest
from sqlalchemy import select

from app.kb.signature import extract_signature
from app.models import KbOccurrence, KbSignature, Run, Task, User

pytestmark = pytest.mark.asyncio

# SSH error whose extract_signature produces signature_key="ssh_connection_failed"
_SSH_ERROR = json.dumps({
    "changed": False,
    "msg": (
        "Failed to connect to the host via ssh: "
        "Warning: Permanently added '100.66.0.108' (ED25519) to the list of known hosts.\r\n"
        "cloudauto@100.66.0.108: Permission denied (publickey)."
    ),
})

# Signature with a DIFFERENT key but representative_text close to the SSH extracted text
# -> similarity() will be strictly between 0 and 1 (not exact, not zero).
_FUZZY_SIG_KEY = "custom_ssh_error"
_FUZZY_SIG_REP = "failed to connect to the host via ssh: permission denied (publickey)"

# Signature with the EXACT key that extract_signature produces -> exact match -> score 1.0
_EXACT_SIG_KEY = "ssh_connection_failed"
_EXACT_SIG_REP = "failed to connect to the host via ssh"


async def _me(db):
    return await db.scalar(select(User).where(User.email == "member@example.com"))


async def _run_with_ssh_task(db, owner):
    run = Run(source="upload", owner_user_id=owner.id, status="failed")
    db.add(run)
    await db.flush()
    db.add(Task(
        run_id=run.id, seq=1, play_name="p", name="Connect",
        status="unreachable", hosts={"h1": "unreachable"}, error=_SSH_ERROR,
    ))
    await db.flush()
    return run


async def test_fuzzy_match_score_is_strictly_between_zero_and_one(authed_client, db):
    """A fuzzy-matched occurrence must return score strictly in (0, 1), not 0.0."""
    me = await _me(db)
    run = await _run_with_ssh_task(db, me)

    sig = KbSignature(
        team_id=None,
        signature_key=_FUZZY_SIG_KEY,
        title="SSH fuzzy",
        status="needs-fix",
        representative_text=_FUZZY_SIG_REP,
    )
    db.add(sig)
    await db.flush()
    db.add(KbOccurrence(signature_id=sig.id, run_id=run.id, task_seq=1, host="h1"))
    await db.flush()

    # Sanity: verify extract_signature gives a DIFFERENT key (not exact)
    extracted = extract_signature(_SSH_ERROR)
    assert extracted is not None
    assert extracted.signature_key != _FUZZY_SIG_KEY, "test setup: must be a fuzzy (not exact) match"

    r = await authed_client.get(f"/api/runs/{run.id}/tasks/1/kb")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body is not None
    assert body["exact"] is False
    score = body["score"]
    assert 0.0 < score < 1.0, f"Expected fuzzy score in (0, 1), got {score}"


async def test_exact_match_score_is_one(authed_client, db):
    """An exact-key match must return score == 1.0 (regression guard)."""
    me = await _me(db)
    run = await _run_with_ssh_task(db, me)

    sig = KbSignature(
        team_id=None,
        signature_key=_EXACT_SIG_KEY,
        title="SSH exact",
        status="known-issue",
        representative_text=_EXACT_SIG_REP,
    )
    db.add(sig)
    await db.flush()
    db.add(KbOccurrence(signature_id=sig.id, run_id=run.id, task_seq=1, host="h1"))
    await db.flush()

    # Sanity: verify extract_signature gives the SAME key (exact match)
    extracted = extract_signature(_SSH_ERROR)
    assert extracted is not None
    assert extracted.signature_key == _EXACT_SIG_KEY, "test setup: must be an exact match"

    r = await authed_client.get(f"/api/runs/{run.id}/tasks/1/kb")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body is not None
    assert body["exact"] is True
    assert body["score"] == 1.0
