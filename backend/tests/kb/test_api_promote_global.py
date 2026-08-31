from __future__ import annotations

from sqlalchemy import func, select

from app.models import AuditLog, KbSignature, Team


async def _mk(db, *, team_id, key="ssh_connection_failed"):
    sig = KbSignature(team_id=team_id, signature_key=key, title="T",
                      status="needs-fix", representative_text="rep")
    db.add(sig)
    await db.flush()
    return sig


async def test_admin_promotes_team_sig_to_global(admin_client, db):
    team = await db.scalar(select(Team).where(Team.is_default.is_(True)))
    sig = await _mk(db, team_id=team.id)
    r = await admin_client.post(f"/api/kb/signatures/{sig.id}/promote-global")
    assert r.status_code == 200, r.text
    assert r.json()["team_id"] is None
    n = await db.scalar(select(func.count()).select_from(AuditLog)
                        .where(AuditLog.action == "kb_promote_global"))
    assert n == 1


async def test_non_admin_promote_global_403(authed_client, db):
    team = await db.scalar(select(Team).where(Team.is_default.is_(True)))
    sig = await _mk(db, team_id=team.id)
    r = await authed_client.post(f"/api/kb/signatures/{sig.id}/promote-global")
    assert r.status_code == 403


async def test_promote_global_missing_404(admin_client):
    import uuid
    r = await admin_client.post(f"/api/kb/signatures/{uuid.uuid4()}/promote-global")
    assert r.status_code == 404


async def test_promote_global_conflict_409(admin_client, db):
    team = await db.scalar(select(Team).where(Team.is_default.is_(True)))
    # a global already owns this key
    await _mk(db, team_id=None, key="dupe_key")
    team_sig = await _mk(db, team_id=team.id, key="dupe_key")
    r = await admin_client.post(f"/api/kb/signatures/{team_sig.id}/promote-global")
    assert r.status_code == 409
