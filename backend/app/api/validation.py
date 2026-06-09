from __future__ import annotations

import uuid

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Team


def parse_uuid_or_422(raw: object, *, detail: str) -> uuid.UUID:
    """uuid.UUID(str(raw)) with ONE canonical exception tuple -> 422."""
    try:
        return uuid.UUID(str(raw))
    except (ValueError, TypeError, AttributeError):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail=detail)


async def resolve_team_or_422(db: AsyncSession, raw: object) -> Team:
    """Parse a raw team id and load the Team; bad id / unknown team -> 422."""
    tid = parse_uuid_or_422(raw, detail="Invalid team_id")
    team = await db.get(Team, tid)
    if team is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail="Unknown team")
    return team
