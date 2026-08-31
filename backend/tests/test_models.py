
import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.models import AuditLog, Session, Team, TeamMember, User


async def test_citext_email_is_case_insensitive(db):
    u = User(email="Mixed.Case@Example.com", password_hash="x", display_name="Mixed")
    db.add(u)
    await db.flush()
    found = await db.scalar(select(User).where(User.email == "mixed.case@example.com"))
    assert found is not None and found.id == u.id


async def test_email_unique_case_insensitive(db):
    db.add(User(email="dup@example.com", password_hash="x", display_name="A"))
    await db.flush()
    db.add(User(email="DUP@example.com", password_hash="x", display_name="B"))
    with pytest.raises(IntegrityError):
        await db.flush()


async def test_created_at_is_timezone_aware(db):
    u = User(email="tz@example.com", password_hash="x", display_name="TZ")
    db.add(u)
    await db.flush()
    await db.refresh(u)
    assert u.created_at.tzinfo is not None


async def test_team_member_composite_pk_dedupes(db):
    u = User(email="m@example.com", password_hash="x", display_name="M")
    t = Team(name="T1", slug="t1")
    db.add_all([u, t])
    await db.flush()
    db.add(TeamMember(team_id=t.id, user_id=u.id))
    await db.flush()
    db.add(TeamMember(team_id=t.id, user_id=u.id))
    with pytest.raises(IntegrityError):
        await db.flush()


async def test_audit_metadata_column_named_metadata(db):
    row = AuditLog(action="test", meta_={"k": "v"})
    db.add(row)
    await db.flush()
    assert AuditLog.__table__.c.metadata.name == "metadata"
    fetched = await db.scalar(select(AuditLog).where(AuditLog.id == row.id))
    assert fetched.meta_ == {"k": "v"}


async def test_session_id_is_opaque_string(db):
    u = User(email="s@example.com", password_hash="x", display_name="S")
    db.add(u)
    await db.flush()
    s = Session(id="opaque-token-abc", user_id=u.id,
                expires_at=__import__("datetime").datetime.now(
                    __import__("datetime").timezone.utc))
    db.add(s)
    await db.flush()
    assert isinstance(s.id, str)
