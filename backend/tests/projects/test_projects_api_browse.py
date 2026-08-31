import asyncio
import os
import shutil
import uuid

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.core.config import settings
from app.core.crypto import encrypt_token
from app.models import AwxController, ControllerTeam, Project, Team
from app.projects import git
from app.projects.storage import project_repo_path
from app.api import projects as projects_api

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git binary not on PATH")


class _RecordingUpload:
    def __init__(self, content: bytes):
        self._content = content
        self._offset = 0
        self.requested_sizes: list[int] = []

    async def read(self, size: int = -1) -> bytes:
        self.requested_sizes.append(size)
        if size < 0:
            size = len(self._content) - self._offset
        chunk = self._content[self._offset:self._offset + size]
        self._offset += len(chunk)
        return chunk


async def test_project_upload_read_is_bounded_before_rejecting(monkeypatch):
    upload = _RecordingUpload(b"abcdef")
    monkeypatch.setattr(settings, "project_upload_max_bytes", 5)

    with pytest.raises(HTTPException) as exc_info:
        await projects_api.upload_files(
            project=object(), request=object(), db=object(), user=object(),
            files=[upload], paths=["file.txt"],
        )

    assert exc_info.value.status_code == 413
    assert upload.requested_sizes
    assert all(0 < size <= 6 for size in upload.requested_sizes)


async def _origin(tmp_path):
    src = tmp_path / "origin"
    src.mkdir()
    env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}

    async def run(*args):
        p = await asyncio.create_subprocess_exec(*args, env=env,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        out, err = await p.communicate()
        assert p.returncode == 0, err.decode()
        return out.decode()

    await run("git", "init", "-q", "-b", "main", str(src))
    (src / "site.yml").write_text("- hosts: all\n")
    await run("git", "-C", str(src), "add", "-A")
    await run("git", "-C", str(src), "commit", "-qm", "c1")
    sha = (await run("git", "-C", str(src), "rev-parse", "HEAD")).strip()
    return src, sha


async def _cloned_project(db, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "projects_data_dir", str(tmp_path / "data"))
    src, sha = await _origin(tmp_path)
    gen = await db.scalar(select(Team).where(Team.is_default.is_(True)))
    c = AwxController(name=f"c-{uuid.uuid4()}", base_url="https://awx.test",
                      auth_token_encrypted=encrypt_token("t"))
    db.add(c); await db.flush()
    db.add(ControllerTeam(controller_id=c.id, team_id=gen.id, awx_organization_id=None))
    p = Project(controller_id=c.id, awx_project_id=19, name="day2", scm_type="git",
                scm_url="https://git.test/day2.git", status="cloned", organization_id=2)
    db.add(p); await db.flush()
    await git.clone_or_fetch(str(src), project_repo_path(p.id), auth_type="none",
                             username=None, secret=None, max_bytes=10**9, timeout=60)
    return p, sha


async def test_tree_and_blob_at_revision(authed_client, db, tmp_path, monkeypatch):
    p, sha = await _cloned_project(db, tmp_path, monkeypatch)
    t = await authed_client.get(f"/api/projects/{p.id}/tree", params={"ref": sha, "path": ""})
    assert t.status_code == 200
    assert any(e["name"] == "site.yml" for e in t.json()["entries"])

    b = await authed_client.get(f"/api/projects/{p.id}/blob", params={"ref": sha, "path": "site.yml"})
    assert b.status_code == 200 and b.json()["content"] == "- hosts: all\n"


async def test_tree_unknown_revision_409(authed_client, db, tmp_path, monkeypatch):
    p, sha = await _cloned_project(db, tmp_path, monkeypatch)
    r = await authed_client.get(f"/api/projects/{p.id}/tree", params={"ref": "f" * 40, "path": ""})
    assert r.status_code == 409


async def test_tree_traversal_422(authed_client, db, tmp_path, monkeypatch):
    p, sha = await _cloned_project(db, tmp_path, monkeypatch)
    r = await authed_client.get(f"/api/projects/{p.id}/tree", params={"ref": "HEAD", "path": "../x"})
    assert r.status_code == 422


async def test_upload_and_browse_uploads(admin_client, db, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "projects_data_dir", str(tmp_path / "data"))
    gen = await db.scalar(select(Team).where(Team.is_default.is_(True)))
    c = AwxController(name=f"c-{uuid.uuid4()}", base_url="https://awx.test",
                      auth_token_encrypted=encrypt_token("t"))
    db.add(c); await db.flush()
    db.add(ControllerTeam(controller_id=c.id, team_id=gen.id, awx_organization_id=None))
    p = Project(controller_id=c.id, awx_project_id=19, name="day2", scm_type="git",
                organization_id=2)
    db.add(p); await db.flush()

    files = [("files", ("main.yml", b"v1\n", "text/yaml"))]
    r = await admin_client.post(f"/api/projects/{p.id}/uploads",
                                files=files, data={"paths": "roles/app/main.yml"})
    assert r.status_code == 201

    t = await admin_client.get(f"/api/projects/{p.id}/tree", params={"ref": "uploads", "path": "roles/app"})
    assert t.status_code == 200
    assert [e["name"] for e in t.json()["entries"]] == ["main.yml"]
    b = await admin_client.get(f"/api/projects/{p.id}/blob", params={"ref": "uploads", "path": "roles/app/main.yml"})
    assert b.json()["content"] == "v1\n"


async def test_upload_traversal_rejected(admin_client, db, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "projects_data_dir", str(tmp_path / "data"))
    gen = await db.scalar(select(Team).where(Team.is_default.is_(True)))
    c = AwxController(name=f"c-{uuid.uuid4()}", base_url="https://awx.test",
                      auth_token_encrypted=encrypt_token("t"))
    db.add(c); await db.flush()
    db.add(ControllerTeam(controller_id=c.id, team_id=gen.id, awx_organization_id=None))
    p = Project(controller_id=c.id, awx_project_id=19, name="day2", organization_id=2)
    db.add(p); await db.flush()
    r = await admin_client.post(f"/api/projects/{p.id}/uploads",
                                files=[("files", ("x", b"x", "text/plain"))],
                                data={"paths": "../evil"})
    assert r.status_code == 422
