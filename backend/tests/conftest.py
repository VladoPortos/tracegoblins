from __future__ import annotations

import os

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncConnection,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import settings as _settings
from app.db.base import Base
from app.db.session import get_db
from app.main import app

# Import models so Base.metadata is fully populated for create_all (added in Task 2).
import app.models as _app_models  # noqa: F401  (no-op import is fine before Task 2 if models pkg exists)

# Disable Secure cookie flag in tests so httpx sends cookies over the http://test transport.
# The CSRF middleware and session cookie helpers read this at request time, so patching the
# singleton here affects all in-process middleware/route code during the test session.
_settings.cookie_secure = False

# Keep the in-process APScheduler off the test event loop. Scheduler logic is covered
# at function level in tests/test_scheduler.py; the app fixtures must never start timers.
_settings.scheduler_enabled = False

# Server-side MFA-enrollment enforcement (MFA1) defaults ON in prod; disable it for the general
# suite (admins in tests have no 2FA) — tests/test_mfa_admin_required_flag.py flips it on per-test.
_settings.mfa_admin_required = False

# Allow .test TLD email addresses in tests (email-validator 2.x flags them as special-use
# unless test_environment=True; the setup/invite tests use *@admin.test / *@example.test).
import email_validator as _ev  # noqa: E402

_ev.TEST_ENVIRONMENT = True

TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://tracegoblins:tracegoblins@localhost:5432/tracegoblins_test",
)
assert TEST_DATABASE_URL.rstrip("/").endswith("_test"), "refusing to run against a non-_test DB"


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def engine():
    eng = create_async_engine(TEST_DATABASE_URL)
    async with eng.begin() as conn:
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS citext"))
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS pg_trgm"))
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield eng
    await eng.dispose()


@pytest_asyncio.fixture(loop_scope="session")
async def db(engine) -> AsyncSession:
    """Per-test session bound to an outer transaction; rolled back after.

    create_savepoint lets app code call session.commit() while the outer
    rollback still undoes everything.
    """
    conn: AsyncConnection = await engine.connect()
    trans = await conn.begin()
    Session = async_sessionmaker(
        bind=conn, expire_on_commit=False, join_transaction_mode="create_savepoint"
    )
    session = Session()
    try:
        yield session
    finally:
        await session.close()
        await trans.rollback()
        await conn.close()


@pytest_asyncio.fixture(loop_scope="session")
async def client(db) -> AsyncClient:
    async def _override_get_db():
        yield db

    app.dependency_overrides[get_db] = _override_get_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()


import secrets
from datetime import datetime, timedelta, timezone

import pytest_asyncio
from sqlalchemy import select

from app.core.config import settings
from app.models import Session as SessionModel, Team, TeamMember, User
from app.security.cookies import sign_session_id
from app.security.passwords import hash_password


async def _get_or_create_general(db):
    t = await db.scalar(select(Team).where(Team.is_default.is_(True)))
    if t is None:
        t = Team(name="General", slug="general", is_default=True)
        db.add(t)
        await db.flush()
    return t


@pytest_asyncio.fixture(loop_scope="session")
async def make_user(db):
    async def _make(
        email="u@example.com", role="user", password="hunter2hunter2",
        display_name=None, must_change_password=False, team=None,
    ):
        team = team or await _get_or_create_general(db)
        user = User(
            email=email, role=role, password_hash=hash_password(password),
            display_name=display_name or email.split("@")[0],
            is_active=True, must_change_password=must_change_password,
        )
        db.add(user)
        await db.flush()
        db.add(TeamMember(team_id=team.id, user_id=user.id))
        await db.flush()
        return user

    return _make


async def _attach_session(client, db, user):
    sid = secrets.token_urlsafe(32)
    db.add(SessionModel(id=sid, user_id=user.id,
                        expires_at=datetime.now(timezone.utc) + timedelta(hours=1)))
    await db.flush()
    csrf = secrets.token_urlsafe(16)
    client.cookies.set(settings.session_cookie_name, sign_session_id(sid))
    client.cookies.set(settings.csrf_cookie_name, csrf)
    client.headers[settings.csrf_header_name] = csrf
    return client


@pytest_asyncio.fixture(loop_scope="session")
async def authed_client(client, db, make_user):
    user = await make_user(email="member@example.com", role="user")
    return await _attach_session(client, db, user)


@pytest_asyncio.fixture(loop_scope="session")
async def admin_client(client, db, make_user):
    admin = await make_user(email="admin@example.com", role="admin")
    return await _attach_session(client, db, admin)


import pytest


@pytest.fixture(autouse=True)
def _reset_limiters():
    from app.security.ratelimit import login_limiter, mfa_verify_limiter, setup_limiter

    for lim in (login_limiter, setup_limiter, mfa_verify_limiter):
        lim.reset_all()
    yield
    for lim in (login_limiter, setup_limiter, mfa_verify_limiter):
        lim.reset_all()


@pytest_asyncio.fixture(loop_scope="session")
async def csrf(client):
    """Prime the anonymous client with a CSRF cookie + matching header (double-submit).

    httpx won't send a Secure cookie over http://test, so we use cookies.set() to
    force-inject the token directly into the jar (same approach as _attach_session).
    The jar is cleared of old csrf_token entries first to avoid CookieConflict when
    called multiple times within the same session-scoped client.
    """
    async def _prime():
        resp = await client.get("/api/auth/csrf")
        # Grab the token from the response Set-Cookie header to avoid a CookieConflict
        # when the jar already has a csrf_token from a previous _prime() call.
        tok = resp.cookies.get(settings.csrf_cookie_name)
        if tok is None:
            # Already had a cookie; read whichever single entry remains.
            tok = client.cookies.get(settings.csrf_cookie_name)
        if tok:
            # Delete all existing csrf_token entries then re-inject without Secure restriction.
            client.cookies.delete(settings.csrf_cookie_name)
            client.cookies.set(settings.csrf_cookie_name, tok)
            client.headers[settings.csrf_header_name] = tok
        return client

    return _prime


@pytest_asyncio.fixture(loop_scope="session")
async def session_for(client, db):
    """Attach a given user's signed session + csrf to the anonymous client."""
    async def _attach(user):
        return await _attach_session(client, db, user)

    return _attach
