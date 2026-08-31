from __future__ import annotations

from pathlib import Path

from sqlalchemy import func, select

from app.models import RunRaw, Task

ROOT = Path(__file__).resolve().parents[2]
UPLOADS = ROOT / "backend/tests/fixtures/logs"


async def _upload(client) -> str:
    text = (UPLOADS / "job_11140.txt").read_text(encoding="utf-8")
    r = await client.post("/api/runs", json={"text": text})
    assert r.status_code == 201
    return r.json()["id"]


async def test_list_pagination_and_ownership(authed_client, client, db, make_user, session_for):
    rid = await _upload(authed_client)
    # verify owner sees their run before switching session_for (shared client)
    lst = await authed_client.get("/api/runs?limit=10&offset=0")
    assert lst.json()["total"] == 1 and lst.json()["items"][0]["id"] == rid
    # the second user sees an empty list (only their own runs)
    other = await make_user(email="other@example.com")
    oc = await session_for(other)
    assert (await oc.get("/api/runs")).json()["total"] == 0


async def test_lean_list_omits_text_full_has_text(authed_client):
    rid = await _upload(authed_client)
    lean = await authed_client.get(f"/api/runs/{rid}/tasks")
    assert lean.status_code == 200
    tasks = lean.json()
    assert len(tasks) == 178 and tasks[0]["seq"] == 1
    assert "output" not in tasks[0] and "error" not in tasks[0]
    # the unreachable task carries error -> full detail exposes it
    fail = next(t for t in tasks if t["status"] == "unreachable")
    full = await authed_client.get(f"/api/runs/{rid}/tasks/{fail['seq']}")
    assert full.status_code == 200 and full.json()["error"] is not None
    assert (await authed_client.get(f"/api/runs/{rid}/tasks/99999")).status_code == 404


async def test_raw_download(authed_client):
    rid = await _upload(authed_client)
    raw = await authed_client.get(f"/api/runs/{rid}/raw")
    assert raw.status_code == 200 and raw.headers["content-type"].startswith("text/plain")
    assert raw.text.startswith("[DEPRECATION WARNING]") or "PLAY [" in raw.text


async def test_delete_cascades_and_404s_after(authed_client, db):
    rid = await _upload(authed_client)
    assert (await authed_client.delete(f"/api/runs/{rid}")).status_code == 204
    import uuid as _uuid
    rid_u = _uuid.UUID(rid)
    assert await db.scalar(select(func.count()).select_from(Task).where(Task.run_id == rid_u)) == 0
    assert await db.scalar(select(func.count()).select_from(RunRaw).where(RunRaw.run_id == rid_u)) == 0
    assert (await authed_client.get(f"/api/runs/{rid}")).status_code == 404


async def test_non_owner_gets_404_everywhere(authed_client, make_user, session_for):
    rid = await _upload(authed_client)
    other = await make_user(email="snoop@example.com")
    oc = await session_for(other)
    for path, method in [
        (f"/api/runs/{rid}", "get"), (f"/api/runs/{rid}/tasks", "get"),
        (f"/api/runs/{rid}/tasks/1", "get"), (f"/api/runs/{rid}/raw", "get"),
        (f"/api/runs/{rid}", "delete"),
    ]:
        resp = await getattr(oc, method)(path)
        assert resp.status_code == 404, f"{method} {path} -> {resp.status_code}"


async def test_admin_does_not_auto_read_others_runs(authed_client, make_user, session_for):
    rid = await _upload(authed_client)
    admin = await make_user(email="admin2@example.com", role="admin")
    ac = await session_for(admin)
    assert (await ac.get(f"/api/runs/{rid}")).status_code == 404  # A1: no admin auto-read
