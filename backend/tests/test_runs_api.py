from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
UPLOADS = ROOT / "backend/tests/fixtures/logs"


async def test_create_run_from_paste(authed_client):
    text = (UPLOADS / "job_11140.txt").read_text(encoding="utf-8")
    r = await authed_client.post("/api/runs", json={"text": text})
    assert r.status_code == 201
    run_id = r.json()["id"]

    detail = await authed_client.get(f"/api/runs/{run_id}")
    assert detail.status_code == 200
    d = detail.json()
    assert d["job_id"] == "11140" and d["status"] == "unreachable"
    assert d["task_count"] == 178 and d["host_count"] == 2
    assert d["counts"]["unreachable"] == 1 and d["counts"]["ok"] == 126


async def test_create_run_from_file(authed_client):
    raw = (UPLOADS / "sample_log-1780472760441.txt").read_bytes()
    r = await authed_client.post(
        "/api/runs",
        files={"file": ("sample.txt", raw, "text/plain")},
        data={"template": "Win Deploy"},
    )
    assert r.status_code == 201
    d = (await authed_client.get(f"/api/runs/{r.json()['id']}")).json()
    assert d["template_name"] == "Win Deploy" and d["status"] == "unreachable"
    assert d["task_count"] == 36


async def test_create_run_paste_requires_text(authed_client):
    r = await authed_client.post("/api/runs", json={"template": "x"})
    assert r.status_code == 422


async def test_create_run_paste_rejects_whitespace_only(authed_client):
    # whitespace-only paste must not persist a junk 0-task run
    assert (await authed_client.post("/api/runs", json={"text": "   \n\t  "})).status_code == 422
    # genuinely empty string still 422s (existing behavior)
    assert (await authed_client.post("/api/runs", json={"text": ""})).status_code == 422


async def test_create_run_whitespace_only_file(authed_client):
    raw = "   \n\t  ".encode("utf-8")
    r = await authed_client.post(
        "/api/runs", files={"file": ("blank.txt", raw, "text/plain")}
    )
    assert r.status_code == 422


async def test_list_runs_pagination_validation(authed_client):
    assert (await authed_client.get("/api/runs?offset=-1")).status_code == 422  # not 500
    assert (await authed_client.get("/api/runs?limit=0")).status_code == 422
    assert (await authed_client.get("/api/runs?limit=101")).status_code == 422
    assert (await authed_client.get("/api/runs?limit=100&offset=0")).status_code == 200
