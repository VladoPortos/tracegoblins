from __future__ import annotations

import uuid

import pytest
from sqlalchemy import func, select

from app.core.config import settings
from app.kb.matcher import MatchResult, match_error
from app.kb.signature import extract_signature
from app.models import KbSignature, Team
from tests.kb._blobs import SSH_BLOB_A, WINRM_BLOB

pytestmark = pytest.mark.asyncio


async def _team(db, name="Team-A", slug="team-a"):
    t = Team(name=name, slug=slug)
    db.add(t)
    await db.flush()
    return t


async def _sig(db, *, team_id, key, rep, title="t", category=None, status="needs-fix"):
    s = KbSignature(
        team_id=team_id, signature_key=key, title=title, category=category,
        status=status, representative_text=rep,
    )
    db.add(s)
    await db.flush()
    return s


async def test_exact_key_wins(db):
    t = await _team(db)
    sig = await _sig(db, team_id=t.id, key="ssh_connection_failed", rep="failed to connect via ssh")
    res = await match_error(db, SSH_BLOB_A, team_ids={t.id})
    assert isinstance(res, MatchResult)
    assert res.exact is True
    assert res.score == 1.0
    assert res.signature.id == sig.id
    assert res.extracted.signature_key == "ssh_connection_failed"


async def test_team_entry_beats_global_on_same_key(db):
    t = await _team(db)
    rep = "failed to connect to the host via ssh"
    await _sig(db, team_id=None, key="ssh_connection_failed", rep=rep, title="global")
    team_sig = await _sig(db, team_id=t.id, key="ssh_connection_failed", rep=rep, title="team")
    res = await match_error(db, SSH_BLOB_A, team_ids={t.id})
    assert res is not None and res.exact is True
    assert res.signature.id == team_sig.id  # team beats global on the tie


async def test_fuzzy_match_above_threshold(db):
    t = await _team(db)
    # No exact key (different key) but the representative_text is near-identical -> fuzzy hit.
    sig = extract_signature(WINRM_BLOB)  # pure/sync; just for the normalized rep text
    # Build a stored signature whose rep is the SAME normalized winrm text but a DIFFERENT key,
    # so the exact-key lookup misses and the fuzzy path is exercised.
    stored = await _sig(db, team_id=t.id, key="winrm_other_key", rep=sig.representative_text)
    res = await match_error(db, WINRM_BLOB, team_ids={t.id})
    assert res is not None
    assert res.exact is False
    assert res.score >= settings.kb_match_threshold
    assert res.signature.id == stored.id


async def test_fuzzy_below_threshold_no_match(db, monkeypatch):
    t = await _team(db)
    # Unrelated representative text -> similarity well below the cutoff -> no match.
    await _sig(db, team_id=t.id, key="totally_unrelated",
               rep="the quick brown fox jumped over thirteen lazy zebras")
    res = await match_error(db, WINRM_BLOB, team_ids={t.id})
    assert res is None


async def test_fuzzy_sub_default_threshold_still_matches(db, monkeypatch):
    # Regression for the % prefilter / GUC mismatch: with KB_MATCH_THRESHOLD set BELOW the
    # Postgres pg_trgm default (0.3), a low-but-above-threshold similarity row MUST still
    # match. match_error issues `SET LOCAL pg_trgm.similarity_threshold = :t` so the %
    # prefilter agrees with the explicit >= check; without it the % operator (stuck at 0.3)
    # would silently drop the row before the >= check ran.
    monkeypatch.setattr(settings, "kb_match_threshold", 0.2)
    t = await _team(db)
    winrm = extract_signature(WINRM_BLOB)  # pure/sync
    # A stored rep that overlaps the WinRM rep only partially -> a low (~0.2-0.3) similarity,
    # i.e. ABOVE the lowered 0.2 cutoff but at/under the 0.3 pg_trgm default. Different key
    # so the exact path misses and the fuzzy path is exercised.
    stored = await _sig(
        db, team_id=t.id, key="winrm_partial",
        rep=winrm.representative_text.split()[0] + " max retries exceeded no route to host",
    )
    # Confirm the row sits in the sub-default band the bug would have dropped.
    sim = await db.scalar(
        select(func.similarity(KbSignature.representative_text, winrm.representative_text))
        .where(KbSignature.id == stored.id)
    )
    assert 0.2 <= float(sim) < 0.3, f"fixture similarity {sim} not in the [0.2, 0.3) regression band"
    res = await match_error(db, WINRM_BLOB, team_ids={t.id})
    assert res is not None and res.exact is False
    assert res.signature.id == stored.id
    assert res.score >= 0.2


async def test_team_a_signature_invisible_to_team_b(db):
    a = await _team(db, name="A", slug="a")
    b = await _team(db, name="B", slug="b")
    await _sig(db, team_id=a.id, key="ssh_connection_failed", rep="failed to connect via ssh")
    # Viewer scoped to team B only -> A's signature must not match (and no global exists).
    res = await match_error(db, SSH_BLOB_A, team_ids={b.id})
    assert res is None


async def test_global_signature_matches_empty_team_scope(db):
    await _sig(db, team_id=None, key="ssh_connection_failed", rep="failed to connect via ssh")
    res = await match_error(db, SSH_BLOB_A, team_ids=set())  # empty -> global-only
    assert res is not None and res.signature.team_id is None


async def test_unextractable_error_returns_none(db):
    res = await match_error(db, None, team_ids={uuid.uuid4()})
    assert res is None
    res2 = await match_error(db, "   ", team_ids=set())
    assert res2 is None
