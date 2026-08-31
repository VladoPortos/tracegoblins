import uuid

from sqlalchemy import select

from app.awx.client import ProjectSummary
from app.awx.projects_sync import sync_projects
from app.core.crypto import encrypt_token
from app.models import AwxController, Project


class _FakeClient:
    def __init__(self, summaries): self._s = summaries
    async def list_projects(self): return self._s


async def _controller(db):
    c = AwxController(name=f"c-{uuid.uuid4()}", base_url="https://awx.test",
                      auth_token_encrypted=encrypt_token("t"))
    db.add(c); await db.flush()
    return c


def _summary(pid, name, rev="a" * 40, org=2):
    return ProjectSummary(id=pid, name=name, description="d", scm_type="git",
                          scm_url=f"https://git.test/{name}.git", scm_branch="main",
                          scm_revision=rev, status="successful",
                          organization_id=org, organization_name="DXC")


async def test_inserts_new_projects(db):
    c = await _controller(db)
    n = await sync_projects(db, c, _FakeClient([_summary(19, "day2"), _summary(10, "hpc")]))
    assert n == 2
    rows = (await db.scalars(select(Project).where(Project.controller_id == c.id))).all()
    assert {r.awx_project_id for r in rows} == {19, 10}
    assert all(r.status == "unlinked" for r in rows)


async def test_resync_refreshes_awx_fields_but_preserves_local(db):
    c = await _controller(db)
    await sync_projects(db, c, _FakeClient([_summary(19, "day2", rev="a" * 40)]))
    p = await db.scalar(select(Project).where(Project.controller_id == c.id))
    # admin links git + a clone happens
    p.status = "cloned"; p.git_url_override = "https://override.test/d.git"
    p.git_auth_type = "token"; p.git_secret_encrypted = encrypt_token("s")
    p.clone_size_bytes = 1234
    await db.flush()

    # AWX revision advances on next sync
    await sync_projects(db, c, _FakeClient([_summary(19, "day2", rev="b" * 40)]))
    await db.refresh(p)
    assert p.scm_revision == "b" * 40            # AWX field refreshed
    assert p.status == "cloned"                  # local field preserved
    assert p.git_url_override == "https://override.test/d.git"
    assert p.git_secret_encrypted is not None
    assert p.clone_size_bytes == 1234
