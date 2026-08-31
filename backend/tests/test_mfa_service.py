from app.models import User
from app.security.passwords import hash_password
from app.services import mfa


async def _user(db) -> User:
    u = User(email=f"u-{id(object())}@x.test", password_hash=hash_password("pw"), display_name="U")
    db.add(u)
    await db.flush()
    return u


async def test_issue_and_consume_recovery_code(db):
    u = await _user(db)
    codes = await mfa.issue_recovery_codes(db, u, n=10)
    assert len(codes) == 10
    assert await mfa.consume_recovery_code(db, u, codes[0]) is True
    assert await mfa.consume_recovery_code(db, u, codes[0]) is False  # one-time use
    assert await mfa.consume_recovery_code(db, u, "nope-nope0") is False


async def test_issue_replaces_previous_set(db):
    u = await _user(db)
    first = await mfa.issue_recovery_codes(db, u, n=10)
    await mfa.issue_recovery_codes(db, u, n=10)  # regenerate replaces
    assert await mfa.consume_recovery_code(db, u, first[0]) is False  # old codes invalidated
