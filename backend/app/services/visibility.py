from __future__ import annotations

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ControllerTeam, Run, RunShare, TeamMember, User


async def my_team_ids(db: AsyncSession, user: User) -> set:
    """The set of team ids U belongs to."""
    return set((await db.execute(
        select(TeamMember.team_id).where(TeamMember.user_id == user.id)
    )).scalars().all())


async def is_run_visible(db: AsyncSession, run: Run, user: User) -> bool:
    """True iff U can see R: owner ∪ team-owned ∪ direct-share ∪ team-share.

    A1: an admin role grants NO path here — visibility is purely relationship-based.
    """
    if run.owner_user_id == user.id:                                   # 1. owner
        return True
    team_ids = await my_team_ids(db, user)
    if run.team_id is not None and run.team_id in team_ids:            # 2. team-owned
        return True
    direct = await db.scalar(select(RunShare.id).where(               # 3. direct share
        RunShare.run_id == run.id, RunShare.shared_with_user_id == user.id).limit(1))
    if direct is not None:
        return True
    if team_ids:                                                       # 4. team share
        team_share = await db.scalar(select(RunShare.id).where(
            RunShare.run_id == run.id,
            RunShare.shared_with_team_id.in_(team_ids)).limit(1))
        if team_share is not None:
            return True
    # 5. AWX run visible via controller_teams (org-aware). team_ids already computed above.
    if run.source == "awx" and run.controller_id is not None and team_ids:
        awx_visible = await db.scalar(
            select(ControllerTeam.id).where(
                ControllerTeam.controller_id == run.controller_id,
                ControllerTeam.team_id.in_(team_ids),
                or_(
                    ControllerTeam.awx_organization_id.is_(None),
                    ControllerTeam.awx_organization_id == run.awx_organization_id,
                ),
            ).limit(1)
        )
        if awx_visible is not None:
            return True
    return False
