from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ControllerTeam, Run, RunShare, TeamMember, User


async def my_team_ids(db: AsyncSession, user: User) -> set:
    """The set of team ids U belongs to."""
    return set((await db.execute(
        select(TeamMember.team_id).where(TeamMember.user_id == user.id)
    )).scalars().all())


def kb_visibility_cond(team_ids: set):
    """KB signature visibility: global (team_id IS NULL) ∪ U-team. Safe for empty team_ids."""
    from app.models import KbSignature

    if team_ids:
        return KbSignature.team_id.is_(None) | KbSignature.team_id.in_(team_ids)
    return KbSignature.team_id.is_(None)


async def run_visible_cond(db: AsyncSession, user: User):
    """A SQL predicate over `Run` matching is_run_visible's five paths for viewer U.

    owner ∪ team-owned ∪ direct-share ∪ team-share ∪ AWX-via-controller_teams.
    A1: admin role grants NO path — purely relationship-based.

    This is THE canonical SQL predicate for single-viewer run visibility — it mirrors
    `is_run_visible` (above) in FULL: the **owner path is INCLUDED**, so a viewer's OWN
    personal uploads count toward "seen in N runs". NOTE: `runs.py::_team_scope_base`
    remains deliberately DIFFERENT — it EXCLUDES the viewer's personal non-AWX uploads
    because it scopes a team's shared view (team-scope semantics), not a single viewer's
    visibility. Keep this aligned with `is_run_visible`, never with `_team_scope_base`.
    """
    team_ids = await my_team_ids(db, user)
    owner = Run.owner_user_id == user.id        # owner path — INCLUDED (unlike _team_scope_base)
    team_owned = Run.team_id.in_(team_ids) if team_ids else sa.false()
    direct = Run.id.in_(
        select(RunShare.run_id).where(RunShare.shared_with_user_id == user.id)
    )
    team_share = (
        Run.id.in_(select(RunShare.run_id).where(RunShare.shared_with_team_id.in_(team_ids)))
        if team_ids else sa.false()
    )
    awx = (
        (Run.source == "awx")
        & Run.controller_id.in_(
            select(ControllerTeam.controller_id).where(
                ControllerTeam.team_id.in_(team_ids),
                or_(
                    ControllerTeam.awx_organization_id.is_(None),
                    ControllerTeam.awx_organization_id == Run.awx_organization_id,
                ),
            )
        )
        if team_ids else sa.false()
    )
    return owner | team_owned | direct | team_share | awx


async def is_run_visible(db: AsyncSession, run: Run, user: User) -> bool:
    """True iff U can see R: owner ∪ team-owned ∪ direct-share ∪ team-share ∪ AWX-via-controller_teams
    (the same 5 branches as run_visible_cond — VIS1).

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


async def project_visible_cond(db: AsyncSession, user: User):
    """SQL predicate over `Project`: visible iff its controller is assigned to a team U is in
    (org-aware), mirroring run-visibility's AWX path #5. Admin role grants NO path; a user in
    no team sees nothing.
    """
    from app.models import Project

    team_ids = await my_team_ids(db, user)
    if not team_ids:
        return sa.false()
    return Project.controller_id.in_(
        select(ControllerTeam.controller_id).where(
            ControllerTeam.team_id.in_(team_ids),
            or_(
                ControllerTeam.awx_organization_id.is_(None),
                ControllerTeam.awx_organization_id == Project.organization_id,
            ),
        )
    )


async def is_project_visible(db: AsyncSession, project, user: User) -> bool:
    """True iff U can see this project: its controller is assigned to one of U's teams, with the
    assignment either all-orgs or matching the project's organization. Mirrors is_run_visible #5.
    """
    team_ids = await my_team_ids(db, user)
    if not team_ids:
        return False
    found = await db.scalar(
        select(ControllerTeam.id).where(
            ControllerTeam.controller_id == project.controller_id,
            ControllerTeam.team_id.in_(team_ids),
            or_(
                ControllerTeam.awx_organization_id.is_(None),
                ControllerTeam.awx_organization_id == project.organization_id,
            ),
        ).limit(1)
    )
    return found is not None
