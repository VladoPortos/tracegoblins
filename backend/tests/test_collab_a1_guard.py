from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
UPLOADS = ROOT / "backend/tests/fixtures/logs"


async def _upload(client) -> str:
    text = (UPLOADS / "job_11140.txt").read_text(encoding="utf-8")
    r = await client.post("/api/runs", json={"text": text})
    assert r.status_code == 201
    return r.json()["id"]


async def test_admin_does_not_auto_read_collab_endpoints(authed_client, make_user, session_for):
    # member@example.com uploads a personal run; capture rid before switching the shared jar.
    rid = await _upload(authed_client)
    admin = await make_user(email="admin-a1@example.com", role="admin")
    ac = await session_for(admin)
    # A1: an admin with no share/team path sees 404 on EVERY collab read for this run.
    for path in [
        f"/api/runs/{rid}/annotations",
        f"/api/runs/{rid}/tasks/1/comments",
        f"/api/runs/{rid}/mentionable",
    ]:
        resp = await ac.get(path)
        assert resp.status_code == 404, f"GET {path} -> {resp.status_code} (A1 breach)"
    # And the admin cannot create collab content either.
    assert (await ac.post(f"/api/runs/{rid}/tasks/1/annotations",
                          json={"note": "x"})).status_code == 404
    assert (await ac.post(f"/api/runs/{rid}/tasks/1/comments",
                          json={"body": "x"})).status_code == 404
