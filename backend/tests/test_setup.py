import pytest
from sqlalchemy import func, select

from app.models import Team, TeamMember, User


async def test_status_true_on_empty_db(client):
    r = await client.get("/api/setup/status")
    assert r.json()["needs_setup"] is True


async def test_setup_creates_admin_general_and_self_locks(client, db):
    payload = {"email": "first@admin.test", "display_name": "First Admin", "password": "sup3r-s3cret-pw"}
    r1 = await client.post("/api/setup", json=payload)
    assert r1.status_code == 201
    assert r1.json()["role"] == "admin"

    admin = await db.scalar(select(User).where(User.email == "first@admin.test"))
    assert admin is not None and admin.role == "admin"
    general = await db.scalar(select(Team).where(Team.is_default.is_(True)))
    assert general is not None and general.name == "General"
    assert await db.scalar(
        select(func.count()).select_from(TeamMember)
        .where(TeamMember.user_id == admin.id, TeamMember.team_id == general.id)
    ) == 1

    # self-lock
    assert (await client.get("/api/setup/status")).json()["needs_setup"] is False
    r2 = await client.post("/api/setup", json={
        "email": "second@admin.test", "display_name": "Nope", "password": "another-pw-1234"})
    assert r2.status_code == 409


async def test_setup_short_password_is_422_not_500(client):
    # AUTH1: a too-short password is a client error (422), not an opaque 500
    r = await client.post("/api/setup", json={
        "email": "a@admin.test", "display_name": "A", "password": "short"})
    assert r.status_code == 422
    assert "at least" in r.json()["detail"].lower()
    # and it must NOT consume the setup window — a valid retry still succeeds (no lockout)
    r2 = await client.post("/api/setup", json={
        "email": "a@admin.test", "display_name": "A", "password": "valid-long-pw-123"})
    assert r2.status_code == 201


@pytest.mark.db_per_test
async def test_setup_is_race_safe():
    """Two concurrent POST /api/setup -> exactly one 201 and one 409 (advisory lock)."""
    import asyncio
    import os

    from httpx import ASGITransport, AsyncClient
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from app.db.base import Base
    from app.db.session import get_db
    from app.main import app

    base = os.environ.get(
        "TEST_DATABASE_URL",
        "postgresql+asyncpg://tracegoblins:tracegoblins@localhost:5432/tracegoblins_test",
    )
    root = base.rsplit("/", 1)[0]
    scratch = root + "/tg_setup_race_test"
    admin_url = root + "/postgres"

    aeng = create_async_engine(admin_url, isolation_level="AUTOCOMMIT")
    async with aeng.connect() as c:
        await c.execute(text("DROP DATABASE IF EXISTS tg_setup_race_test"))
        await c.execute(text("CREATE DATABASE tg_setup_race_test"))
    await aeng.dispose()

    eng = create_async_engine(scratch)
    async with eng.begin() as conn:
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS citext"))
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS pg_trgm"))
        await conn.run_sync(Base.metadata.create_all)
    Maker = async_sessionmaker(eng, expire_on_commit=False)

    async def _override():
        async with Maker() as s:
            yield s

    app.dependency_overrides[get_db] = _override
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            payloads = [
                {"email": f"race{i}@admin.test", "display_name": f"R{i}", "password": "race-pass-1234"}
                for i in range(2)
            ]
            results = await asyncio.gather(*[c.post("/api/setup", json=p) for p in payloads])
            assert sorted(r.status_code for r in results) == [201, 409]
    finally:
        app.dependency_overrides.clear()
        await eng.dispose()
        aeng = create_async_engine(admin_url, isolation_level="AUTOCOMMIT")
        async with aeng.connect() as c:
            await c.execute(text("DROP DATABASE IF EXISTS tg_setup_race_test"))
        await aeng.dispose()
