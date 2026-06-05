from __future__ import annotations

import secrets
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models import Session


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def create_session(
    db: AsyncSession, *, user_id: uuid.UUID, ip: str | None, user_agent: str | None, remember: bool
) -> Session:
    absolute = (
        timedelta(days=settings.session_remember_days)
        if remember
        else timedelta(hours=settings.session_absolute_hours)
    )
    sess = Session(
        id=secrets.token_urlsafe(32),
        user_id=user_id,
        expires_at=_now() + absolute,
        ip=ip,
        user_agent=(user_agent or "")[:512] or None,
    )
    db.add(sess)
    await db.flush()
    return sess


async def get_valid_session(db: AsyncSession, session_id: str) -> Session | None:
    # Use select() rather than db.get() so bulk-update revocations (which bypass the
    # ORM identity map) are always visible without a manual expire/refresh cycle.
    sess = await db.scalar(select(Session).where(Session.id == session_id))
    if sess is None or sess.revoked_at is not None:
        return None
    now = _now()
    if now >= sess.expires_at:
        return None
    if now >= sess.last_seen_at + timedelta(minutes=settings.session_idle_minutes):
        return None
    return sess


async def touch_session(db: AsyncSession, sess: Session) -> None:
    # Must COMMIT, not just flush: current_user() runs this on every authenticated request,
    # but read-only routes (GETs) never call db.commit(), so a flushed-only last_seen_at is
    # discarded when the request session closes. Active users doing mostly GETs would then
    # still idle out. Committing here (throttled to once per touch_throttle_seconds) makes the
    # idle-window refresh durable. It only persists this row's last_seen_at — current_user runs
    # before the route body, so nothing else is pending in the session at this point.
    if (_now() - sess.last_seen_at).total_seconds() >= settings.touch_throttle_seconds:
        sess.last_seen_at = _now()
        await db.commit()


async def revoke_session(db: AsyncSession, session_id: str) -> None:
    await db.execute(
        update(Session)
        .where(Session.id == session_id, Session.revoked_at.is_(None))
        .values(revoked_at=_now())
    )


async def revoke_all_for_user(
    db: AsyncSession, user_id: uuid.UUID, *, except_session_id: str | None = None
) -> None:
    stmt = update(Session).where(Session.user_id == user_id, Session.revoked_at.is_(None))
    if except_session_id:
        stmt = stmt.where(Session.id != except_session_id)
    await db.execute(stmt.values(revoked_at=_now()))
