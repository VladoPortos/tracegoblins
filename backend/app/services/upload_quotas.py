from __future__ import annotations

import uuid

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models import Run, User


async def enforce_upload_quota(
    db: AsyncSession, *, user_id: uuid.UUID, incoming_bytes: int
) -> None:
    """Serialize and check a user's uploaded-run quota in the current transaction."""
    # The row lock is held through the caller's insert + commit. Concurrent uploads for the
    # same user therefore see the preceding upload after waiting instead of both passing a
    # stale count/sum check.
    await db.scalar(select(User.id).where(User.id == user_id).with_for_update())
    count, used_bytes = (
        await db.execute(
            select(
                func.count(Run.id),
                func.coalesce(func.sum(Run.upload_size_bytes), 0),
            ).where(Run.owner_user_id == user_id, Run.source == "upload")
        )
    ).one()

    if count >= settings.user_upload_max_runs:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Upload quota exceeded: maximum stored run count reached",
        )
    if int(used_bytes) + incoming_bytes > settings.user_upload_max_bytes:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Upload quota exceeded: maximum stored bytes reached",
        )
