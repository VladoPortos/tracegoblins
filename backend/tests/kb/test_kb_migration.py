import os

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine


@pytest.mark.db_per_test
async def test_migration_0006_knowledge_base():
    """upgrade head -> downgrade base -> upgrade head must round-trip cleanly and leave
    kb_signatures (both partial-unique indexes + the GIN trgm index) and kb_occurrences
    (dedupe unique constraint + lookup indexes)."""
    import asyncio

    from alembic import command
    from alembic.config import Config

    base_url = os.environ.get(
        "TEST_DATABASE_URL",
        "postgresql+asyncpg://tracegoblins:tracegoblins@localhost:5432/tracegoblins_test",
    )
    scratch = base_url.rsplit("/", 1)[0] + "/tracegoblins_mig0006_test"
    admin = base_url.rsplit("/", 1)[0] + "/postgres"

    eng = create_async_engine(admin, isolation_level="AUTOCOMMIT")
    async with eng.connect() as conn:
        await conn.execute(text("DROP DATABASE IF EXISTS tracegoblins_mig0006_test"))
        await conn.execute(text("CREATE DATABASE tracegoblins_mig0006_test"))
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
        tables = (await conn.execute(text(
            "SELECT table_name FROM information_schema.tables WHERE table_schema='public'"
        ))).scalars().all()
        for t in ("kb_signatures", "kb_occurrences"):
            assert t in tables, f"{t} missing after upgrade 0006"

        sig_idxs = (await conn.execute(text(
            "SELECT indexname FROM pg_indexes WHERE tablename='kb_signatures'"
        ))).scalars().all()
        for idx in ("uq_kb_signatures_team_key", "uq_kb_signatures_global_key",
                    "ix_kb_signatures_team", "ix_kb_signatures_status",
                    "ix_kb_signatures_rep_trgm"):
            assert idx in sig_idxs, f"{idx} missing after 0006"

        # The representative_text index must be a GIN index (pg_trgm fuzzy target).
        rep_using = (await conn.execute(text(
            "SELECT am.amname FROM pg_class c "
            "JOIN pg_index i ON i.indexrelid = c.oid "
            "JOIN pg_class t ON t.oid = i.indrelid "
            "JOIN pg_am am ON am.oid = c.relam "
            "WHERE c.relname = 'ix_kb_signatures_rep_trgm'"
        ))).scalar_one()
        assert rep_using == "gin", f"ix_kb_signatures_rep_trgm should be GIN, got {rep_using!r}"

        # Both signature partial-unique indexes carry a WHERE predicate (NULL-distinct trick).
        partial = (await conn.execute(text(
            "SELECT indexname FROM pg_indexes WHERE tablename='kb_signatures' "
            "AND indexdef LIKE '%WHERE%'"
        ))).scalars().all()
        assert "uq_kb_signatures_team_key" in partial
        assert "uq_kb_signatures_global_key" in partial

        occ_idxs = (await conn.execute(text(
            "SELECT indexname FROM pg_indexes WHERE tablename='kb_occurrences'"
        ))).scalars().all()
        for idx in ("ix_kb_occurrences_signature", "ix_kb_occurrences_run"):
            assert idx in occ_idxs, f"{idx} missing after 0006"

        occ_uq = (await conn.execute(text(
            "SELECT conname FROM pg_constraint WHERE conname='uq_kb_occurrences_sig_run_seq'"
        ))).scalars().all()
        assert occ_uq == ["uq_kb_occurrences_sig_run_seq"]

        # pg_trgm survives the downgrade (0004 owns it; 0006 must not drop it).
        ext = (await conn.execute(text(
            "SELECT extname FROM pg_extension WHERE extname='pg_trgm'"
        ))).scalars().all()
        assert ext == ["pg_trgm"]
    await eng.dispose()

    eng = create_async_engine(admin, isolation_level="AUTOCOMMIT")
    async with eng.connect() as conn:
        await conn.execute(text("DROP DATABASE IF EXISTS tracegoblins_mig0006_test"))
    await eng.dispose()
