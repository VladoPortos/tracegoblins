"""Task A5 — Run AWX columns + owner_user_id nullable tests."""
from sqlalchemy import select, text

from app.models import Run, User


async def _user(db, email="run_col_u@example.com"):
    u = User(email=email, password_hash="x", display_name=email.split("@")[0])
    db.add(u)
    await db.flush()
    return u


async def test_owner_user_id_is_nullable_in_model(db):
    """owner_user_id=None is accepted by the ORM (AWX runs are owner-less)."""
    run = Run(source="awx", owner_user_id=None, status="successful",
              host_count=0, task_count=0, warnings_count=0, recap=[])
    db.add(run)
    await db.flush()
    got = await db.scalar(select(Run).where(Run.id == run.id))
    assert got.owner_user_id is None


async def test_owner_user_id_nullable_in_information_schema(db):
    """information_schema confirms owner_user_id IS_NULLABLE='YES' in the DB."""
    row = await db.execute(
        text(
            "SELECT is_nullable FROM information_schema.columns "
            "WHERE table_name='runs' AND column_name='owner_user_id'"
        )
    )
    is_nullable = row.scalar_one()
    assert is_nullable == "YES", f"expected YES, got {is_nullable!r}"


async def test_awx_columns_default_to_none(db):
    """New AWX filter columns default to NULL for upload runs."""
    user = await _user(db, "awx_col_owner@example.com")
    run = Run(source="upload", owner_user_id=user.id, status="ok",
              host_count=0, task_count=0, warnings_count=0, recap=[])
    db.add(run)
    await db.flush()
    got = await db.scalar(select(Run).where(Run.id == run.id))
    assert got.awx_organization_id is None
    assert got.awx_organization_name is None
    assert got.awx_launch_type is None
    assert got.awx_workflow_name is None


async def test_awx_columns_roundtrip(db):
    """AWX filter columns persist correctly for a simulated AWX run."""
    run = Run(
        source="awx",
        owner_user_id=None,
        status="successful",
        host_count=2,
        task_count=5,
        warnings_count=0,
        recap=[],
        awx_organization_id=7,
        awx_organization_name="DXC",
        awx_launch_type="scheduled",
        awx_workflow_name="nightly-deploy",
    )
    db.add(run)
    await db.flush()
    got = await db.scalar(select(Run).where(Run.id == run.id))
    assert got.awx_organization_id == 7
    assert got.awx_organization_name == "DXC"
    assert got.awx_launch_type == "scheduled"
    assert got.awx_workflow_name == "nightly-deploy"
    assert got.owner_user_id is None
