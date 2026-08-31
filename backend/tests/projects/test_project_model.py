import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.models import AwxController, Project
from app.core.crypto import encrypt_token


async def _controller(db):
    c = AwxController(name=f"c-{uuid.uuid4()}", base_url="https://awx.test",
                      auth_token_encrypted=encrypt_token("t"))
    db.add(c)
    await db.flush()
    return c


async def test_project_defaults_and_roundtrip(db):
    c = await _controller(db)
    p = Project(controller_id=c.id, awx_project_id=19, name="day2actions_repo",
                scm_type="git", scm_url="https://git.test/day2.git", organization_id=2)
    db.add(p)
    await db.flush()
    got = await db.scalar(select(Project).where(Project.id == p.id))
    assert got.status == "unlinked"
    assert got.git_auth_type is None
    assert got.git_secret_encrypted is None


async def test_unique_controller_awx_project(db):
    c = await _controller(db)
    db.add(Project(controller_id=c.id, awx_project_id=19, name="a", scm_type="git"))
    await db.flush()
    db.add(Project(controller_id=c.id, awx_project_id=19, name="b", scm_type="git"))
    with pytest.raises(IntegrityError):
        await db.flush()
