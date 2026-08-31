from __future__ import annotations

import json

from sqlalchemy import func, select

from app.models import AuditLog, KbOccurrence, Run, Task, Team, User

SSH_ERR = json.dumps({
    "changed": False,
    "msg": "Failed to connect to the host via ssh: Warning: Permanently added "
           "'100.66.0.108' (ED25519) to the list of known hosts.\r\n"
           "Load key \"/tmp/ansible._7oamnkx_ssh_cert\": invalid format\r\n"
           "cloudauto@100.66.0.108: Permission denied (publickey).",
})


async def _me(db):
    return await db.scalar(select(User).where(User.email == "member@example.com"))


async def _run_with_failed_task(db, owner, *, team_id=None, error=SSH_ERR):
    run = Run(source="upload", owner_user_id=owner.id, team_id=team_id,
              status="failed", template_name="Deploy")
    db.add(run)
    await db.flush()
    db.add(Task(run_id=run.id, seq=1, play_name="p", name="connect", status="unreachable",
                hosts={"web-1": "unreachable"}, error=error, line_no=1))
    await db.flush()
    return run


async def test_promote_auto_extracts_and_backfills(authed_client, db):
    me = await _me(db)
    team = await db.scalar(select(Team).where(Team.is_default.is_(True)))
    run = await _run_with_failed_task(db, me, team_id=team.id)
    r = await authed_client.post("/api/kb/promote", json={
        "run_id": str(run.id), "task_seq": 1, "team_id": str(team.id),
        "title": "SSH unreachable", "status": "known-issue",
        "links": [{"label": "Runbook", "url": "https://wiki/ssh"}],
    })
    assert r.status_code == 201, r.text
    body = r.json()
    # server re-extracted -> client cannot spoof the key
    assert body["signature_key"] == "ssh_connection_failed"
    assert body["category"] == "connectivity"
    assert body["title"] == "SSH unreachable"
    # backfill recorded the originating run as an occurrence
    sig_id = body["id"]
    n = await db.scalar(select(func.count()).select_from(KbOccurrence)
                        .where(KbOccurrence.signature_id == sig_id))
    assert n == 1
    assert body["occurrence_count"] == 1
    a = await db.scalar(select(func.count()).select_from(AuditLog).where(AuditLog.action == "kb_promote"))
    assert a == 1


async def test_promote_no_extractable_error_422(authed_client, db):
    me = await _me(db)
    team = await db.scalar(select(Team).where(Team.is_default.is_(True)))
    run = await _run_with_failed_task(db, me, team_id=team.id, error=None)
    r = await authed_client.post("/api/kb/promote", json={
        "run_id": str(run.id), "task_seq": 1, "team_id": str(team.id), "title": "X",
    })
    assert r.status_code == 422


async def test_promote_invisible_run_404(authed_client, db, make_user):
    other = await make_user(email="promoteowner@example.com")
    run = await _run_with_failed_task(db, other)
    r = await authed_client.post("/api/kb/promote", json={
        "run_id": str(run.id), "task_seq": 1, "title": "X",
    })
    assert r.status_code == 404


async def test_promote_global_requires_admin(authed_client, db):
    me = await _me(db)
    run = await _run_with_failed_task(db, me)
    r = await authed_client.post("/api/kb/promote", json={
        "run_id": str(run.id), "task_seq": 1, "team_id": None, "title": "X",
    })
    assert r.status_code == 403


async def test_promote_javascript_link_422(authed_client, db):
    me = await _me(db)
    team = await db.scalar(select(Team).where(Team.is_default.is_(True)))
    run = await _run_with_failed_task(db, me, team_id=team.id)
    r = await authed_client.post("/api/kb/promote", json={
        "run_id": str(run.id), "task_seq": 1, "team_id": str(team.id), "title": "X",
        "links": [{"label": "x", "url": "javascript:1"}],
    })
    assert r.status_code == 422
