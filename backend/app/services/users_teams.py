from __future__ import annotations

import uuid

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Team, TeamMember

# Transaction-scoped advisory lock serializing every "must keep ≥1 team per user" check.
# Without it, removing a user from two teams concurrently (or a remove racing a team delete)
# each sees count==2 and both proceed -> the user ends with zero teams (TOCTOU on the
# every-user-∈-≥1-team invariant). One global lock is fine — these are rare admin ops.
_TEAM_INVARIANT_LOCK = 0x54475F54  # "TG_T"


async def _lock_team_invariant(db: AsyncSession) -> None:
    await db.execute(text("SELECT pg_advisory_xact_lock(:k)").bindparams(k=_TEAM_INVARIANT_LOCK))


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
    await _lock_team_invariant(db)  # serialize the last-team check vs. concurrent removals
    if await count_user_teams(db, user_id) <= 1:
        raise LastTeamError()
    tm = await db.get(TeamMember, (team_id, user_id))
    if tm is not None:
        await db.delete(tm)
        await db.flush()


async def delete_team(db: AsyncSession, team: Team) -> None:
    if team.is_default:
        raise DefaultTeamError()
    await _lock_team_invariant(db)  # serialize the per-member last-team check vs. concurrent ops
    member_ids = (
        await db.execute(select(TeamMember.user_id).where(TeamMember.team_id == team.id))
    ).scalars().all()
    for uid in member_ids:
        if await count_user_teams(db, uid) <= 1:
            raise LastTeamError()
    # FK ondelete=CASCADE removes team_members rows when the team is deleted.
    await db.delete(team)
    await db.flush()
