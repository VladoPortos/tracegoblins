from __future__ import annotations

import uuid

from app.models import KbSignature, Team


async def _mk_sig(db, *, team_id, key="ssh_connection_failed", rep="failed to connect via ssh"):
    sig = KbSignature(
        team_id=team_id, signature_key=key, title="SSH down",
        status="needs-fix", representative_text=rep,
    )
    db.add(sig)
    await db.flush()
    return sig


async def test_get_global_signature_visible_to_any_user(authed_client, db):
    sig = await _mk_sig(db, team_id=None)
    r = await authed_client.get(f"/api/kb/signatures/{sig.id}")
    assert r.status_code == 200
    body = r.json()
    assert body["id"] == str(sig.id)
    assert body["team_id"] is None
    assert body["signature_key"] == "ssh_connection_failed"
    assert body["occurrence_count"] == 0


async def test_get_own_team_signature_visible(authed_client, db):
    # authed_client's user is in the default General team via the make_user fixture.
    team = await db.scalar(__import__("sqlalchemy").select(Team).where(Team.is_default.is_(True)))
    sig = await _mk_sig(db, team_id=team.id, key="winrm_connection_failed")
    r = await authed_client.get(f"/api/kb/signatures/{sig.id}")
    assert r.status_code == 200
    assert r.json()["team_id"] == str(team.id)


async def test_get_other_team_signature_404_not_403(authed_client, db):
    # A signature owned by a team the caller is NOT a member of -> 404 (A1, no leak).
    other = Team(name="Strangers", slug="strangers")
    db.add(other)
    await db.flush()
    sig = await _mk_sig(db, team_id=other.id, key="assertion_failed")
    r = await authed_client.get(f"/api/kb/signatures/{sig.id}")
    assert r.status_code == 404


async def test_get_missing_signature_404(authed_client):
    r = await authed_client.get(f"/api/kb/signatures/{uuid.uuid4()}")
    assert r.status_code == 404
