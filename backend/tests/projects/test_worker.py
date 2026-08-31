from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from app.awx.sync import controller_lock_key
from app.core.crypto import encrypt_token
from app.models import AwxController, Project
from app.projects import worker


def _session_factory(db):
    class _CM:
        async def __aenter__(self): return db
        async def __aexit__(self, *exc): return False
    return lambda: _CM()


async def _project(db, **over):
    c = AwxController(name=f"c-{uuid.uuid4()}", base_url="https://awx.test",
                      auth_token_encrypted=encrypt_token("t"))
    db.add(c); await db.flush()
    fields = dict(controller_id=c.id, awx_project_id=19, name="day2", scm_type="git",
                  scm_url="https://git.test/day2.git", status="pending")
    fields.update(over)
    p = Project(**fields)
    db.add(p); await db.flush()
    return p


async def test_projects_to_refetch_includes_cloned_and_stale_orphans(db):
    # REL1: routine refresh (cloned) + crash-orphaned pending/cloning (stale), but NOT a fresh
    # pending project that a clone may still be actively working.
    from datetime import timedelta
    from app.core.clock import utcnow
    old = utcnow() - timedelta(minutes=worker._STALE_CLONE_MINUTES + 5)
    cloned = await _project(db, status="cloned", awx_project_id=1)
    stale_pending = await _project(db, status="pending", awx_project_id=2, updated_at=old)
    stale_cloning = await _project(db, status="cloning", awx_project_id=3, updated_at=old)
    fresh_pending = await _project(db, status="pending", awx_project_id=4)  # updated_at ≈ now
    await db.flush()
    ids = set(await worker._projects_to_refetch(db))
    assert {cloned.id, stale_pending.id, stale_cloning.id} <= ids
    assert fresh_pending.id not in ids


def test_project_lock_key_namespaced():
    pid = uuid.uuid4()
    assert worker.project_lock_key(pid) != controller_lock_key(pid)
    assert worker.project_lock_key(pid) == worker.project_lock_key(str(pid))


async def test_run_clone_success(db, monkeypatch):
    p = await _project(db)

    async def _fake_clone(source_url, repo_path, **kw):
        assert source_url == "https://git.test/day2.git"
        return 4096, "main"

    monkeypatch.setattr(worker, "clone_or_fetch", _fake_clone)
    # run_clone opens its own SessionLocal; point it at the test session.
    monkeypatch.setattr(worker, "SessionLocal", _session_factory(db))

    await worker.run_clone(str(p.id))
    await db.refresh(p)
    assert p.status == "cloned" and p.clone_size_bytes == 4096 and p.last_clone_error is None


async def test_run_clone_records_error(db, monkeypatch):
    p = await _project(db)

    async def _boom(source_url, repo_path, **kw):
        from app.projects.git import GitError
        raise GitError("boom")

    monkeypatch.setattr(worker, "clone_or_fetch", _boom)
    monkeypatch.setattr(worker, "SessionLocal", _session_factory(db))
    await worker.run_clone(str(p.id))
    await db.refresh(p)
    assert p.status == "error" and "boom" in (p.last_clone_error or "")


async def test_failed_refetch_keeps_existing_clone_available(db, tmp_path, monkeypatch):
    from app.core.config import settings
    from app.projects.git import GitError

    monkeypatch.setattr(settings, "projects_data_dir", str(tmp_path / "projects"))
    p = await _project(db, status="cloned")
    repo = worker.project_repo_path(p.id)
    repo.mkdir(parents=True)
    (repo / "HEAD").write_text("ref: refs/heads/main\n")

    async def _boom(source_url, repo_path, **kw):
        raise GitError("temporary fetch failure")

    monkeypatch.setattr(worker, "clone_or_fetch", _boom)
    monkeypatch.setattr(worker, "SessionLocal", _session_factory(db))

    await worker.run_clone(str(p.id))
    await db.refresh(p)

    assert p.status == "cloned"
    assert "temporary fetch failure" in (p.last_clone_error or "")


async def test_run_clone_rejects_non_https(db, monkeypatch):
    p = await _project(db, scm_url="git@git.test:day2.git", git_url_override=None)
    monkeypatch.setattr(worker, "SessionLocal", _session_factory(db))
    await worker.run_clone(str(p.id))
    await db.refresh(p)
    assert p.status == "error" and "https" in (p.last_clone_error or "").lower()
