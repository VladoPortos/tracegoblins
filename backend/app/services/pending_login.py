from __future__ import annotations

import uuid
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.clock import utcnow
from app.core.config import settings
from app.models import PendingLogin


async def create_pending(
    db: AsyncSession, *, user_id: uuid.UUID, remember: bool, ip: str | None, user_agent: str | None
) -> PendingLogin:
    row = PendingLogin(
        user_id=user_id,
        remember=remember,
        ip=ip,
        user_agent=(user_agent or "")[:512] or None,
        expires_at=utcnow() + timedelta(minutes=settings.mfa_pending_ttl_minutes),
    )
    db.add(row)
    await db.flush()
    return row


async def get_valid_pending(db: AsyncSession, pending_id: str) -> PendingLogin | None:
    try:
        pid = uuid.UUID(pending_id)
    except (ValueError, TypeError):
        return None
    # Lock the row FOR UPDATE so the read→consume window can't be raced into a double-consume
    # (mirrors the invite-row pattern). Belt-and-suspenders today (WEB_CONCURRENCY=1), correct
    # if the app is ever scaled to multiple workers.
    row = await db.scalar(select(PendingLogin).where(PendingLogin.id == pid).with_for_update())
    if row is None or row.consumed_at is not None or utcnow() >= row.expires_at:
        return None
    return row


async def consume_pending(db: AsyncSession, row: PendingLogin) -> bool:
    if row.consumed_at is not None:
        return False
    row.consumed_at = utcnow()
    await db.flush()
    return True
