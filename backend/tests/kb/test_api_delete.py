from __future__ import annotations

from sqlalchemy import func, select

from app.models import AuditLog, KbOccurrence, KbSignature, Run, Team


async def _mk(db, *, team_id, key="ssh_connection_failed"):
    sig = KbSignature(team_id=team_id, signature_key=key, title="T",
                      status="needs-fix", representative_text="rep")
    db.add(sig)
    await db.flush()
    return sig


async def test_member_deletes_team_signature(authed_client, db):
    team = await db.scalar(select(Team).where(Team.is_default.is_(True)))
    sig = await _mk(db, team_id=team.id)
    r = await authed_client.delete(f"/api/kb/signatures/{sig.id}")
    assert r.status_code == 204
    assert await db.get(KbSignature, sig.id) is None
    n = await db.scalar(select(func.count()).select_from(AuditLog).where(AuditLog.action == "kb_delete"))
    assert n == 1


async def test_non_member_delete_other_team_404(authed_client, db):
    other = Team(name="NotYours", slug="notyours")
    db.add(other)
    await db.flush()
    sig = await _mk(db, team_id=other.id)
    r = await authed_client.delete(f"/api/kb/signatures/{sig.id}")
    assert r.status_code == 404


async def test_non_admin_delete_global_403(authed_client, db):
    sig = await _mk(db, team_id=None)
    r = await authed_client.delete(f"/api/kb/signatures/{sig.id}")
    assert r.status_code == 403


async def test_admin_deletes_global(admin_client, db):
    sig = await _mk(db, team_id=None)
    r = await admin_client.delete(f"/api/kb/signatures/{sig.id}")
    assert r.status_code == 204


async def test_delete_cascades_occurrences(authed_client, db):
    """Deleting a signature removes its kb_occurrences (FK ondelete=CASCADE)."""
    team = await db.scalar(select(Team).where(Team.is_default.is_(True)))
    sig = await _mk(db, team_id=team.id, key="cascade_route_key")
    run = Run(status="failed", source="upload")
    db.add(run)
    await db.flush()
    db.add(KbOccurrence(signature_id=sig.id, run_id=run.id, task_seq=2, host="h"))
    await db.flush()
    sig_id = sig.id
    r = await authed_client.delete(f"/api/kb/signatures/{sig_id}")
    assert r.status_code == 204
    await db.rollback()  # fresh read after the route's commit
    remaining = (await db.scalars(
        select(KbOccurrence).where(KbOccurrence.signature_id == sig_id)
    )).all()
    assert remaining == []
