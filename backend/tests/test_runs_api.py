from __future__ import annotations

from pathlib import Path

from sqlalchemy import select

from app.core.config import settings
from app.models import Run, User

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


async def test_uploaded_run_records_original_byte_size(authed_client, db):
    text = (UPLOADS / "job_11140.txt").read_text(encoding="utf-8")
    response = await authed_client.post("/api/runs", json={"text": text})

    assert response.status_code == 201
    run = await db.get(Run, response.json()["id"])
    assert run.upload_size_bytes == len(text.encode("utf-8"))


async def test_upload_run_count_quota_is_enforced(authed_client, db, monkeypatch):
    user = await db.scalar(select(User).where(User.email == "member@example.com"))
    db.add(Run(
        source="upload",
        owner_user_id=user.id,
        status="ok",
        upload_size_bytes=1,
    ))
    await db.flush()
    monkeypatch.setattr(settings, "user_upload_max_runs", 1)
    monkeypatch.setattr(settings, "user_upload_max_bytes", 1024 * 1024 * 1024)

    text = (UPLOADS / "job_11140.txt").read_text(encoding="utf-8")
    response = await authed_client.post("/api/runs", json={"text": text})

    assert response.status_code == 429
    assert "quota" in response.json()["detail"].lower()


async def test_upload_byte_quota_is_enforced(authed_client, monkeypatch):
    text = (UPLOADS / "job_11140.txt").read_text(encoding="utf-8")
    monkeypatch.setattr(settings, "user_upload_max_runs", 200)
    monkeypatch.setattr(settings, "user_upload_max_bytes", len(text.encode("utf-8")) - 1)

    response = await authed_client.post("/api/runs", json={"text": text})

    assert response.status_code == 429
    assert "quota" in response.json()["detail"].lower()


async def test_deleting_upload_releases_quota(authed_client, db, monkeypatch):
    user = await db.scalar(select(User).where(User.email == "member@example.com"))
    existing = Run(
        source="upload",
        owner_user_id=user.id,
        status="ok",
        upload_size_bytes=1,
    )
    db.add(existing)
    await db.flush()
    monkeypatch.setattr(settings, "user_upload_max_runs", 1)
    monkeypatch.setattr(settings, "user_upload_max_bytes", 1024 * 1024 * 1024)

    deleted = await authed_client.delete(f"/api/runs/{existing.id}")
    text = (UPLOADS / "job_11140.txt").read_text(encoding="utf-8")
    uploaded = await authed_client.post("/api/runs", json={"text": text})

    assert deleted.status_code == 204
    assert uploaded.status_code == 201


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
