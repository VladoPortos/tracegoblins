from datetime import datetime, timedelta, timezone

from app.models import User
from app.security.passwords import hash_password
from app.services import pending_login as pl


async def _user(db) -> User:
    u = User(email=f"p-{id(object())}@x.test", password_hash=hash_password("pw"), display_name="P")
    db.add(u)
    await db.flush()
    return u


async def test_create_get_consume(db):
    u = await _user(db)
    row = await pl.create_pending(db, user_id=u.id, remember=True, ip="1.2.3.4", user_agent="t")
    got = await pl.get_valid_pending(db, str(row.id))
    assert got is not None and got.remember is True
    assert await pl.consume_pending(db, row) is True
    assert await pl.get_valid_pending(db, str(row.id)) is None  # consumed -> invalid
    assert await pl.consume_pending(db, row) is False  # double-consume guarded


async def test_expired_pending_is_invalid(db):
    u = await _user(db)
    row = await pl.create_pending(db, user_id=u.id, remember=False, ip=None, user_agent=None)
    row.expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
    await db.flush()
    assert await pl.get_valid_pending(db, str(row.id)) is None
