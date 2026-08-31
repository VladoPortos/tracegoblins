import os

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine


@pytest.mark.db_per_test
async def test_migration_0014_up_and_down():
    import asyncio

    from alembic import command
    from alembic.config import Config

    base_url = os.environ.get(
        "TEST_DATABASE_URL",
        "postgresql+asyncpg://tracegoblins:tracegoblins@localhost:5432/tracegoblins_test",
    )
    scratch = base_url.rsplit("/", 1)[0] + "/tracegoblins_mig0014_test"
    admin = base_url.rsplit("/", 1)[0] + "/postgres"

    eng = create_async_engine(admin, isolation_level="AUTOCOMMIT")
    async with eng.connect() as conn:
        await conn.execute(text("DROP DATABASE IF EXISTS tracegoblins_mig0014_test"))
        await conn.execute(text("CREATE DATABASE tracegoblins_mig0014_test"))
    await eng.dispose()

    def _alembic(target):
        cfg = Config("alembic.ini")
        cfg.set_main_option("script_location", "alembic")
        os.environ["DATABASE_URL"] = scratch
        if target == "down":
            command.downgrade(cfg, "0013")
        else:
            command.upgrade(cfg, target)

    # upgrade head → projects + runs link index exist
    await asyncio.to_thread(_alembic, "head")
    eng = create_async_engine(scratch)
    async with eng.connect() as conn:
        cols = (await conn.execute(text(
            "SELECT column_name FROM information_schema.columns WHERE table_name='projects'"
        ))).scalars().all()
        assert {"git_secret_encrypted", "git_url_override", "status", "clone_size_bytes"} <= set(cols)
        idx = (await conn.execute(text(
            "SELECT indexname FROM pg_indexes WHERE tablename='runs'"
        ))).scalars().all()
        assert "ix_runs_controller_project" in idx
    await eng.dispose()

    # downgrade to 0013 → projects table gone
    await asyncio.to_thread(_alembic, "down")
    eng = create_async_engine(scratch)
    async with eng.connect() as conn:
        tables = (await conn.execute(text(
            "SELECT table_name FROM information_schema.tables WHERE table_schema='public'"
        ))).scalars().all()
        assert "projects" not in tables
    await eng.dispose()

    eng = create_async_engine(admin, isolation_level="AUTOCOMMIT")
    async with eng.connect() as conn:
        await conn.execute(text("DROP DATABASE IF EXISTS tracegoblins_mig0014_test"))
    await eng.dispose()
