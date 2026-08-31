import os

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine


@pytest.mark.db_per_test
async def test_migrations_apply_and_reverse_cleanly():
    """alembic upgrade head then downgrade base must run without error.

    Run via the alembic Config in a thread (alembic drives its own event loop).
    Uses a scratch database so it doesn't collide with the create_all test schema.
    """
    import asyncio

    from alembic import command
    from alembic.config import Config

    base_url = os.environ.get(
        "TEST_DATABASE_URL",
        "postgresql+asyncpg://tracegoblins:tracegoblins@localhost:5432/tracegoblins_test",
    )
    # Use a dedicated scratch DB name to avoid clobbering the suite schema.
    scratch = base_url.rsplit("/", 1)[0] + "/tracegoblins_mig_test"
    admin = base_url.rsplit("/", 1)[0] + "/postgres"

    eng = create_async_engine(admin, isolation_level="AUTOCOMMIT")
    async with eng.connect() as conn:
        await conn.execute(text("DROP DATABASE IF EXISTS tracegoblins_mig_test"))
        await conn.execute(text("CREATE DATABASE tracegoblins_mig_test"))
    await eng.dispose()

    def _run():
        cfg = Config("alembic.ini")
        cfg.set_main_option("script_location", "alembic")
        # env.py reads DATABASE_URL at call time, so this points alembic at the scratch DB
        # (not the suite's create_all DB) — preventing 'relation already exists' collisions.
        os.environ["DATABASE_URL"] = scratch
        command.upgrade(cfg, "head")
        command.downgrade(cfg, "base")

    await asyncio.to_thread(_run)

    eng = create_async_engine(admin, isolation_level="AUTOCOMMIT")
    async with eng.connect() as conn:
        await conn.execute(text("DROP DATABASE IF EXISTS tracegoblins_mig_test"))
    await eng.dispose()


@pytest.mark.db_per_test
async def test_migration_0003_creates_collab_tables_and_team_index():
    """upgrade head must leave run_shares/annotations/comments/notifications + ix_runs_team_created."""
    import asyncio

    from alembic import command
    from alembic.config import Config

    base_url = os.environ.get(
        "TEST_DATABASE_URL",
        "postgresql+asyncpg://tracegoblins:tracegoblins@localhost:5432/tracegoblins_test",
    )
    scratch = base_url.rsplit("/", 1)[0] + "/tracegoblins_mig0003_test"
    admin = base_url.rsplit("/", 1)[0] + "/postgres"

    eng = create_async_engine(admin, isolation_level="AUTOCOMMIT")
    async with eng.connect() as conn:
        await conn.execute(text("DROP DATABASE IF EXISTS tracegoblins_mig0003_test"))
        await conn.execute(text("CREATE DATABASE tracegoblins_mig0003_test"))
    await eng.dispose()

    def _run():
        cfg = Config("alembic.ini")
        cfg.set_main_option("script_location", "alembic")
        os.environ["DATABASE_URL"] = scratch
        command.upgrade(cfg, "head")

    await asyncio.to_thread(_run)

    eng = create_async_engine(scratch)
    async with eng.connect() as conn:
        tables = (await conn.execute(text(
            "SELECT table_name FROM information_schema.tables WHERE table_schema='public'"
        ))).scalars().all()
        for t in ("run_shares", "annotations", "comments", "notifications"):
            assert t in tables, f"{t} missing after upgrade head"
        idx = (await conn.execute(text(
            "SELECT indexname FROM pg_indexes WHERE tablename='runs'"
        ))).scalars().all()
        assert "ix_runs_team_created" in idx
        chk = (await conn.execute(text(
            "SELECT conname FROM pg_constraint WHERE conname='ck_run_shares_exactly_one_target'"
        ))).scalars().all()
        assert chk == ["ck_run_shares_exactly_one_target"]
        fk = (await conn.execute(text(
            "SELECT conname FROM pg_constraint WHERE conname='fk_runs_team_id_teams'"
        ))).scalars().all()
        assert fk == ["fk_runs_team_id_teams"]  # runs.team_id FK activated in 0003
    await eng.dispose()

    eng = create_async_engine(admin, isolation_level="AUTOCOMMIT")
    async with eng.connect() as conn:
        await conn.execute(text("DROP DATABASE IF EXISTS tracegoblins_mig0003_test"))
    await eng.dispose()


@pytest.mark.db_per_test
async def test_migration_0004_awx_sync():
    """upgrade head must leave awx_controllers, controller_teams, AWX runs columns,
    nullable owner_user_id, FK fk_runs_controller_id_awx_controllers, and the 5 filter indexes."""
    import asyncio

    from alembic import command
    from alembic.config import Config

    base_url = os.environ.get(
        "TEST_DATABASE_URL",
        "postgresql+asyncpg://tracegoblins:tracegoblins@localhost:5432/tracegoblins_test",
    )
    scratch = base_url.rsplit("/", 1)[0] + "/tracegoblins_mig0004_test"
    admin = base_url.rsplit("/", 1)[0] + "/postgres"

    eng = create_async_engine(admin, isolation_level="AUTOCOMMIT")
    async with eng.connect() as conn:
        await conn.execute(text("DROP DATABASE IF EXISTS tracegoblins_mig0004_test"))
        await conn.execute(text("CREATE DATABASE tracegoblins_mig0004_test"))
    await eng.dispose()

    def _run():
        cfg = Config("alembic.ini")
        cfg.set_main_option("script_location", "alembic")
        os.environ["DATABASE_URL"] = scratch
        command.upgrade(cfg, "head")
        command.downgrade(cfg, "base")
        command.upgrade(cfg, "head")

    await asyncio.to_thread(_run)

    eng = create_async_engine(scratch)
    async with eng.connect() as conn:
        # Tables exist
        tables = (await conn.execute(text(
            "SELECT table_name FROM information_schema.tables WHERE table_schema='public'"
        ))).scalars().all()
        for t in ("awx_controllers", "controller_teams"):
            assert t in tables, f"{t} missing after upgrade 0004"

        # owner_user_id is nullable
        is_nullable = (await conn.execute(text(
            "SELECT is_nullable FROM information_schema.columns "
            "WHERE table_name='runs' AND column_name='owner_user_id'"
        ))).scalar_one()
        assert is_nullable == "YES", f"owner_user_id should be nullable, got {is_nullable!r}"

        # AWX columns exist on runs
        cols = (await conn.execute(text(
            "SELECT column_name FROM information_schema.columns WHERE table_name='runs'"
        ))).scalars().all()
        for col in ("awx_organization_id", "awx_organization_name", "awx_launch_type", "awx_workflow_name"):
            assert col in cols, f"runs.{col} missing after 0004"

        # Filter indexes exist
        run_idxs = (await conn.execute(text(
            "SELECT indexname FROM pg_indexes WHERE tablename='runs'"
        ))).scalars().all()
        for idx in ("ix_runs_controller_created", "ix_runs_org", "ix_runs_status",
                    "ix_runs_awx_user", "ix_runs_template_trgm"):
            assert idx in run_idxs, f"{idx} missing after 0004"

        # FK fk_runs_controller_id_awx_controllers exists
        fk = (await conn.execute(text(
            "SELECT conname FROM pg_constraint "
            "WHERE conname='fk_runs_controller_id_awx_controllers'"
        ))).scalars().all()
        assert fk == ["fk_runs_controller_id_awx_controllers"]

        # Partial unique indexes for controller_teams
        ct_idxs = (await conn.execute(text(
            "SELECT indexname FROM pg_indexes WHERE tablename='controller_teams'"
        ))).scalars().all()
        assert "uq_controller_teams_specific" in ct_idxs
        assert "uq_controller_teams_allorgs" in ct_idxs

    await eng.dispose()

    eng = create_async_engine(admin, isolation_level="AUTOCOMMIT")
    async with eng.connect() as conn:
        await conn.execute(text("DROP DATABASE IF EXISTS tracegoblins_mig0004_test"))
    await eng.dispose()
