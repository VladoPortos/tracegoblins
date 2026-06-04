from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Team, TeamMember


class LastTeamError(Exception):
    """Raised when an op would leave a user with zero teams."""


class DefaultTeamError(Exception):
    """Raised when an op targets the default (General) team illegally."""


async def count_user_teams(db: AsyncSession, user_id: uuid.UUID) -> int:
    return await db.scalar(
        select(func.count()).select_from(TeamMember).where(TeamMember.user_id == user_id)
    )


async def add_member(db: AsyncSession, team_id: uuid.UUID, user_id: uuid.UUID) -> bool:
    """Add membership. Returns False if it already existed (idempotent)."""
    if await db.get(TeamMember, (team_id, user_id)) is not None:
        return False
    db.add(TeamMember(team_id=team_id, user_id=user_id))
    await db.flush()
    return True


async def remove_member(db: AsyncSession, team_id: uuid.UUID, user_id: uuid.UUID) -> None:
    if await count_user_teams(db, user_id) <= 1:
        raise LastTeamError()
    tm = await db.get(TeamMember, (team_id, user_id))
    if tm is not None:
        await db.delete(tm)
        await db.flush()


async def delete_team(db: AsyncSession, team: Team) -> None:
    if team.is_default:
        raise DefaultTeamError()
    member_ids = (
        await db.execute(select(TeamMember.user_id).where(TeamMember.team_id == team.id))
    ).scalars().all()
    for uid in member_ids:
        if await count_user_teams(db, uid) <= 1:
            raise LastTeamError()
    # FK ondelete=CASCADE removes team_members rows when the team is deleted.
    await db.delete(team)
    await db.flush()
