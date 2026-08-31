from datetime import datetime, timedelta, timezone

from app.models import User
from app.services.sessions import (
    create_session,
    get_valid_session,
    revoke_all_for_user,
    revoke_session,
)


async def _user(db):
    u = User(email="sess@example.com", password_hash="x", display_name="Sess")
    db.add(u)
    await db.flush()
    return u


async def test_create_and_validate(db):
    u = await _user(db)
    s = await create_session(db, user_id=u.id, ip="1.2.3.4", user_agent="UA", remember=False)
    assert len(s.id) >= 40
    got = await get_valid_session(db, s.id)
    assert got is not None and got.id == s.id


async def test_revoked_session_is_invalid(db):
    u = await _user(db)
    s = await create_session(db, user_id=u.id, ip=None, user_agent=None, remember=False)
    await revoke_session(db, s.id)
    assert await get_valid_session(db, s.id) is None


async def test_expired_session_is_invalid(db):
    u = await _user(db)
    s = await create_session(db, user_id=u.id, ip=None, user_agent=None, remember=False)
    s.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    await db.flush()
    assert await get_valid_session(db, s.id) is None


async def test_idle_timeout(db):
    u = await _user(db)
    s = await create_session(db, user_id=u.id, ip=None, user_agent=None, remember=False)
    s.last_seen_at = datetime.now(timezone.utc) - timedelta(days=999)
    await db.flush()
    assert await get_valid_session(db, s.id) is None


async def test_revoke_all_except(db):
    u = await _user(db)
    keep = await create_session(db, user_id=u.id, ip=None, user_agent=None, remember=False)
    drop = await create_session(db, user_id=u.id, ip=None, user_agent=None, remember=False)
    await revoke_all_for_user(db, u.id, except_session_id=keep.id)
    assert await get_valid_session(db, keep.id) is not None
    assert await get_valid_session(db, drop.id) is None
