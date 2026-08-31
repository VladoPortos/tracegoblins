from __future__ import annotations

import json

from app.models import Run, Task

SSH_ERR = json.dumps({
    "changed": False,
    "msg": "Failed to connect to the host via ssh: Warning: Permanently added "
           "'100.66.0.108' (ED25519) to the list of known hosts.\r\n"
           "Load key \"/tmp/ansible._7oamnkx_ssh_cert\": invalid format\r\n"
           "cloudauto@100.66.0.108: Permission denied (publickey).",
})


async def _run_with_task(db, owner, *, error):
    run = Run(source="upload", owner_user_id=owner.id, status="failed", template_name="Deploy")
    db.add(run)
    await db.flush()
    db.add(Task(run_id=run.id, seq=1, play_name="p", name="connect", status="unreachable",
                hosts={"web-1": "unreachable"}, error=error, line_no=1))
    await db.flush()
    return run


async def test_suggest_returns_extracted_signature(authed_client, db, make_user):
    await make_user(email="suggester@example.com")
    # the authed_client user owns it so it's visible; reuse authed_client's user.
    from app.models import User
    me = await db.scalar(__import__("sqlalchemy").select(User).where(User.email == "member@example.com"))
    run = await _run_with_task(db, me, error=SSH_ERR)
    r = await authed_client.get(f"/api/kb/suggest?run_id={run.id}&task_seq=1")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["signature_key"] == "ssh_connection_failed"
    assert body["category"] == "connectivity"
    assert "<ip>" in body["representative_text"] or "100.66.0.108" not in body["representative_text"]


async def test_suggest_invisible_run_404(authed_client, db, make_user, session_for):
    other = await make_user(email="otherown@example.com")
    run = await _run_with_task(db, other, error=SSH_ERR)
    # authed_client is NOT the owner and has no share -> 404
    r = await authed_client.get(f"/api/kb/suggest?run_id={run.id}&task_seq=1")
    assert r.status_code == 404


async def test_suggest_missing_task_404(authed_client, db):
    from app.models import User
    me = await db.scalar(__import__("sqlalchemy").select(User).where(User.email == "member@example.com"))
    run = await _run_with_task(db, me, error=SSH_ERR)
    r = await authed_client.get(f"/api/kb/suggest?run_id={run.id}&task_seq=999")
    assert r.status_code == 404


async def test_suggest_no_extractable_error_422(authed_client, db):
    from app.models import User
    me = await db.scalar(__import__("sqlalchemy").select(User).where(User.email == "member@example.com"))
    run = await _run_with_task(db, me, error=None)
    r = await authed_client.get(f"/api/kb/suggest?run_id={run.id}&task_seq=1")
    assert r.status_code == 422
