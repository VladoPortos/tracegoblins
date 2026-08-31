from __future__ import annotations

import json

from sqlalchemy import select

from app.models import KbOccurrence, KbSignature, Run, Task, Team, User

SSH_ERR = json.dumps({
    "changed": False,
    "msg": "Failed to connect to the host via ssh: Warning: Permanently added "
           "'100.66.0.108' (ED25519) to the list of known hosts.\r\n"
           "cloudauto@100.66.0.108: Permission denied (publickey).",
})


async def _me(db):
    return await db.scalar(select(User).where(User.email == "member@example.com"))


async def _run_task(db, owner, *, error=SSH_ERR):
    run = Run(source="upload", owner_user_id=owner.id, status="failed", template_name="Deploy")
    db.add(run)
    await db.flush()
    db.add(Task(run_id=run.id, seq=1, play_name="p", name="connect", status="unreachable",
                hosts={"web-1": "unreachable"}, error=error, line_no=1))
    await db.flush()
    return run


async def test_drawer_returns_card_when_occurrence_exists(authed_client, db):
    me = await _me(db)
    run = await _run_task(db, me)
    sig = KbSignature(team_id=None, signature_key="ssh_connection_failed",
                      title="SSH down", status="known-issue",
                      representative_text="failed to connect to the host via ssh")
    db.add(sig)
    await db.flush()
    db.add(KbOccurrence(signature_id=sig.id, run_id=run.id, task_seq=1, host="web-1"))
    await db.flush()

    r = await authed_client.get(f"/api/runs/{run.id}/tasks/1/kb")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body is not None
    assert body["signature"]["signature_key"] == "ssh_connection_failed"
    assert body["signature"]["occurrence_count"] == 1
    assert body["exact"] is True and body["score"] == 1.0


async def test_drawer_returns_null_when_no_occurrence(authed_client, db):
    me = await _me(db)
    run = await _run_task(db, me)
    r = await authed_client.get(f"/api/runs/{run.id}/tasks/1/kb")
    assert r.status_code == 200
    assert r.json() is None


async def test_drawer_hides_occurrence_for_invisible_signature(authed_client, db):
    # An occurrence pointing at a signature of a team U is NOT in must NOT surface.
    me = await _me(db)
    run = await _run_task(db, me)
    other = Team(name="Hidden", slug="hidden")
    db.add(other)
    await db.flush()
    sig = KbSignature(team_id=other.id, signature_key="ssh_connection_failed",
                      title="Hidden", status="needs-fix",
                      representative_text="failed to connect to the host via ssh")
    db.add(sig)
    await db.flush()
    db.add(KbOccurrence(signature_id=sig.id, run_id=run.id, task_seq=1, host="web-1"))
    await db.flush()
    r = await authed_client.get(f"/api/runs/{run.id}/tasks/1/kb")
    assert r.status_code == 200
    assert r.json() is None  # signature not visible -> drawer shows no card


async def test_drawer_invisible_run_404(authed_client, db, make_user):
    other = await make_user(email="drawerother@example.com")
    run = await _run_task(db, other)
    r = await authed_client.get(f"/api/runs/{run.id}/tasks/1/kb")
    assert r.status_code == 404  # VisibleRun gate
