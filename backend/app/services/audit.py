from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AuditLog


async def write_audit(
    db: AsyncSession,
    *,
    action: str,
    actor_id: uuid.UUID | None = None,
    target_type: str | None = None,
    target_id: str | None = None,
    ip: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> None:
    """Append an audit row. Caller owns the transaction (does NOT commit)."""
    db.add(AuditLog(
        actor_id=actor_id,
        action=action,
        target_type=target_type,
        target_id=target_id,
        ip=ip,
        meta_=metadata or {},
    ))
