"""Task A4 — AwxController + ControllerTeam model tests."""

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.models import AwxController, ControllerTeam, Team, User


async def _user(db, email="awx_u@example.com"):
    u = User(email=email, password_hash="x", display_name=email.split("@")[0])
    db.add(u)
    await db.flush()
    return u


async def _team(db, name="AWXTeam", slug="awxteam"):
    t = Team(name=name, slug=slug)
    db.add(t)
    await db.flush()
    return t


async def _controller(db, name="awx-ctrl", created_by=None):
    c = AwxController(
        name=name,
        base_url="https://awx.example.com",
        auth_token_encrypted="gAAAAAFake==",
    )
    if created_by:
        c.created_by_user_id = created_by.id
    db.add(c)
    await db.flush()
    return c


async def test_awx_controller_defaults(db):
    """AwxController persists with correct server/model defaults."""
    ctrl = await _controller(db, name="ctrl-defaults")
    got = await db.scalar(select(AwxController).where(AwxController.id == ctrl.id))
    assert got.verify_ssl is True
    assert got.sync_mode == "manual"
    assert got.sync_interval_minutes is None
    assert got.last_synced_job_id is None
    assert got.last_sync_at is None
    assert got.last_sync_status == "never"
    assert got.last_sync_error is None
    assert got.status == "unconfigured"
    assert got.created_by_user_id is None
    assert got.created_at is not None
    assert got.updated_at is not None


async def test_awx_controller_with_creator(db):
    """AwxController.created_by_user_id stores the creator UUID."""
    user = await _user(db, "creator@example.com")
    ctrl = await _controller(db, name="ctrl-with-creator", created_by=user)
    got = await db.scalar(select(AwxController).where(AwxController.id == ctrl.id))
    assert got.created_by_user_id == user.id


async def test_awx_controller_name_unique(db):
    """Two controllers with the same name raise IntegrityError."""
    await _controller(db, name="unique-name")
    with pytest.raises(IntegrityError):
        async with db.begin_nested():
            await _controller(db, name="unique-name")


async def test_awx_controller_delete_cascades_team_links(db):
    """Deleting a controller cascades to its ControllerTeam rows."""
    from sqlalchemy import func
    ctrl = await _controller(db, name="ctrl-cascade")
    team = await _team(db, name="CascadeTeam", slug="cascadeteam")
    ct = ControllerTeam(controller_id=ctrl.id, team_id=team.id)
    db.add(ct)
    await db.flush()
    await db.delete(ctrl)
    await db.flush()
    count = await db.scalar(
        select(func.count()).select_from(ControllerTeam).where(
            ControllerTeam.controller_id == ctrl.id
        )
    )
    assert count == 0


async def test_controller_team_specific_org_roundtrip(db):
    """ControllerTeam with awx_organization_id set persists correctly."""
    ctrl = await _controller(db, name="ctrl-specific")
    team = await _team(db, name="SpecificTeam", slug="specificteam")
    ct = ControllerTeam(controller_id=ctrl.id, team_id=team.id, awx_organization_id=42)
    db.add(ct)
    await db.flush()
    got = await db.scalar(select(ControllerTeam).where(ControllerTeam.id == ct.id))
    assert got.awx_organization_id == 42
    assert got.created_at is not None


async def test_controller_team_all_orgs_roundtrip(db):
    """ControllerTeam with awx_organization_id=None (all orgs) persists."""
    ctrl = await _controller(db, name="ctrl-allorgs")
    team = await _team(db, name="AllOrgsTeam", slug="allorgs-team")
    ct = ControllerTeam(controller_id=ctrl.id, team_id=team.id, awx_organization_id=None)
    db.add(ct)
    await db.flush()
    got = await db.scalar(select(ControllerTeam).where(ControllerTeam.id == ct.id))
    assert got.awx_organization_id is None


async def test_controller_team_specific_org_unique_enforced(db):
    """Two rows with same (controller, team, org_id) raise IntegrityError."""
    ctrl = await _controller(db, name="ctrl-uq-specific")
    team = await _team(db, name="UqSpecific", slug="uq-specific")
    db.add(ControllerTeam(controller_id=ctrl.id, team_id=team.id, awx_organization_id=10))
    await db.flush()
    with pytest.raises(IntegrityError):
        async with db.begin_nested():
            db.add(ControllerTeam(controller_id=ctrl.id, team_id=team.id, awx_organization_id=10))
            await db.flush()


async def test_controller_team_allorgs_unique_enforced(db):
    """Two all-orgs rows for same (controller, team) raise IntegrityError."""
    ctrl = await _controller(db, name="ctrl-uq-allorgs")
    team = await _team(db, name="UqAllOrgs", slug="uq-allorgs")
    db.add(ControllerTeam(controller_id=ctrl.id, team_id=team.id, awx_organization_id=None))
    await db.flush()
    with pytest.raises(IntegrityError):
        async with db.begin_nested():
            db.add(ControllerTeam(controller_id=ctrl.id, team_id=team.id, awx_organization_id=None))
            await db.flush()


async def test_controller_team_specific_and_allorgs_coexist(db):
    """A specific-org row and an all-orgs row for same (controller, team) can coexist."""
    ctrl = await _controller(db, name="ctrl-coexist")
    team = await _team(db, name="Coexist", slug="coexist")
    db.add(ControllerTeam(controller_id=ctrl.id, team_id=team.id, awx_organization_id=99))
    db.add(ControllerTeam(controller_id=ctrl.id, team_id=team.id, awx_organization_id=None))
    await db.flush()  # no IntegrityError expected


def test_controller_has_sync_progress_columns():
    from app.models import AwxController
    cols = AwxController.__table__.c
    assert "sync_total" in cols and cols["sync_total"].nullable
    assert "sync_done" in cols and cols["sync_done"].nullable
    assert "sync_current_job" in cols and cols["sync_current_job"].nullable
