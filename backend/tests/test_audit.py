from sqlalchemy import select

from app.models import AuditLog
from app.services.audit import write_audit


async def test_write_audit_adds_row_without_committing(db):
    await write_audit(db, action="login", ip="1.2.3.4", metadata={"email": "a@b.c"})
    await db.flush()
    row = await db.scalar(select(AuditLog).where(AuditLog.action == "login"))
    assert row is not None
    assert row.ip == "1.2.3.4"
    assert row.meta_ == {"email": "a@b.c"}
