from __future__ import annotations

from sqlalchemy import func, select

from app.models import AuditLog, KbSignature, Team


async def _mk(db, *, team_id, key="ssh_connection_failed"):
    sig = KbSignature(team_id=team_id, signature_key=key, title="Old",
                      status="needs-fix", representative_text="rep")
    db.add(sig)
    await db.flush()
    return sig


async def test_member_edits_team_signature(authed_client, db):
    team = await db.scalar(select(Team).where(Team.is_default.is_(True)))
    sig = await _mk(db, team_id=team.id)
    r = await authed_client.patch(f"/api/kb/signatures/{sig.id}", json={
        "title": "New title", "status": "resolved",
        "links": [{"label": "Doc", "url": "https://wiki/x"}],
    })
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["title"] == "New title" and body["status"] == "resolved"
    assert body["links"][0]["url"] == "https://wiki/x"
    n = await db.scalar(select(func.count()).select_from(AuditLog).where(AuditLog.action == "kb_edit"))
    assert n == 1


async def test_edit_representative_text_prunes_stale_occurrences(authed_client, db):
    # KB1: changing the match target must drop occurrences that no longer match, instead of leaving
    # them to permanently inflate "seen in N runs".
    from app.models import KbOccurrence, Run, User
    team = await db.scalar(select(Team).where(Team.is_default.is_(True)))
    sig = await _mk(db, team_id=team.id)
    member = await db.scalar(select(User).where(User.email == "member@example.com"))
    run = Run(source="upload", status="failed", owner_user_id=member.id, team_id=team.id)
    db.add(run); await db.flush()
    # a stale occurrence for a run with no matching failed tasks (won't re-match on backfill)
    db.add(KbOccurrence(signature_id=sig.id, run_id=run.id, task_seq=0, host="h1"))
    await db.commit()
    before = await db.scalar(select(func.count()).select_from(KbOccurrence)
                             .where(KbOccurrence.signature_id == sig.id))
    assert before == 1
    r = await authed_client.patch(f"/api/kb/signatures/{sig.id}",
                                  json={"representative_text": "totally different unmatchable text"})
    assert r.status_code == 200, r.text
    after = await db.scalar(select(func.count()).select_from(KbOccurrence)
                            .where(KbOccurrence.signature_id == sig.id))
    assert after == 0   # the stale occurrence was pruned (no run re-matches the new text)


async def test_non_member_edit_other_team_404(authed_client, db):
    other = Team(name="Theirs", slug="theirs")
    db.add(other)
    await db.flush()
    sig = await _mk(db, team_id=other.id)
    r = await authed_client.patch(f"/api/kb/signatures/{sig.id}", json={"title": "x"})
    assert r.status_code == 404  # not visible -> 404, never reveals existence


async def test_non_admin_edit_global_403(authed_client, db):
    sig = await _mk(db, team_id=None)  # global; visible to all but only admin may edit
    r = await authed_client.patch(f"/api/kb/signatures/{sig.id}", json={"title": "x"})
    assert r.status_code == 403


async def test_admin_edits_global(admin_client, db):
    sig = await _mk(db, team_id=None)
    r = await admin_client.patch(f"/api/kb/signatures/{sig.id}", json={"title": "Admin edit"})
    assert r.status_code == 200
    assert r.json()["title"] == "Admin edit"


async def test_edit_bad_status_422(admin_client, db):
    sig = await _mk(db, team_id=None)
    r = await admin_client.patch(f"/api/kb/signatures/{sig.id}", json={"status": "nope"})
    assert r.status_code == 422


async def test_edit_javascript_link_422(admin_client, db):
    sig = await _mk(db, team_id=None)
    r = await admin_client.patch(f"/api/kb/signatures/{sig.id}",
                                 json={"links": [{"label": "x", "url": "javascript:1"}]})
    assert r.status_code == 422


# --- explicit-null guard on NOT-NULL columns ---

async def test_explicit_null_title_422(authed_client, db):
    team = await db.scalar(select(Team).where(Team.is_default.is_(True)))
    sig = await _mk(db, team_id=team.id)
    r = await authed_client.patch(f"/api/kb/signatures/{sig.id}", json={"title": None})
    assert r.status_code == 422


async def test_explicit_null_status_422(authed_client, db):
    team = await db.scalar(select(Team).where(Team.is_default.is_(True)))
    sig = await _mk(db, team_id=team.id)
    r = await authed_client.patch(f"/api/kb/signatures/{sig.id}", json={"status": None})
    assert r.status_code == 422


async def test_explicit_null_representative_text_422(authed_client, db):
    team = await db.scalar(select(Team).where(Team.is_default.is_(True)))
    sig = await _mk(db, team_id=team.id)
    r = await authed_client.patch(f"/api/kb/signatures/{sig.id}", json={"representative_text": None})
    assert r.status_code == 422


async def test_partial_update_nullable_field_200(authed_client, db):
    """Omitting NOT-NULL fields and nulling a genuinely-nullable field must still succeed."""
    team = await db.scalar(select(Team).where(Team.is_default.is_(True)))
    sig = await _mk(db, team_id=team.id)
    r = await authed_client.patch(f"/api/kb/signatures/{sig.id}",
                                  json={"description": None, "title": "Updated"})
    assert r.status_code == 200
    body = r.json()
    assert body["title"] == "Updated"
    assert body["description"] is None
