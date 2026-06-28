from __future__ import annotations

import re
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import TeamBrief
from app.api.deps import AdminUser, DbSession, require_password_current
from app.api.http_utils import client_ip
from app.models import Team, TeamMember, User
from app.services.audit import write_audit
from app.services.sessions import revoke_all_for_user
from app.services.users_teams import (
    DefaultTeamError,
    LastTeamError,
    add_member,
    delete_team,
    remove_member,
)

router = APIRouter(
    prefix="/api/admin", tags=["admin"], dependencies=[Depends(require_password_current)]
)


class UserOut(BaseModel):
    id: str
    email: str
    display_name: str
    role: str
    is_active: bool
    created_at: datetime
    last_login_at: datetime | None
    teams: list[TeamBrief]
    totp_enabled: bool = False
    initials: str | None = None
    avatar_color: str | None = None


class RoleIn(BaseModel):
    role: str


async def _teams_for(db: AsyncSession, user_id: uuid.UUID) -> list[TeamBrief]:
    rows = (
        await db.execute(
            select(Team).join(TeamMember, TeamMember.team_id == Team.id)
            .where(TeamMember.user_id == user_id).order_by(Team.name)
        )
    ).scalars().all()
    return [TeamBrief.of(t) for t in rows]


async def _user_out(db: AsyncSession, user: User) -> UserOut:
    return UserOut(
        id=str(user.id), email=user.email, display_name=user.display_name, role=user.role,
        is_active=user.is_active, created_at=user.created_at,
        last_login_at=user.last_login_at,
        teams=await _teams_for(db, user.id),
        totp_enabled=user.totp_enabled,
        initials=user.initials,
        avatar_color=user.avatar_color,
    )


@router.get("/users", response_model=list[UserOut])
async def list_users(admin: AdminUser, db: DbSession):
    users = (await db.execute(select(User).order_by(User.created_at))).scalars().all()
    return [await _user_out(db, u) for u in users]


# Transaction-scoped advisory lock that serializes every "must keep ≥1 active admin" check.
# Without it, two concurrent demotions/deactivations each read count==1 (excluding the OTHER
# admin) and both proceed -> zero admins (a TOCTOU on a documented invariant). Auto-released
# when the route's transaction commits/rolls back.
_ADMIN_INVARIANT_LOCK = 0x54475F41  # "TG_A"


async def _lock_admin_invariant(db: AsyncSession) -> None:
    await db.execute(text("SELECT pg_advisory_xact_lock(:k)").bindparams(k=_ADMIN_INVARIANT_LOCK))


async def _active_admin_count(db: AsyncSession, *, exclude_id: uuid.UUID | None = None) -> int:
    stmt = select(func.count()).select_from(User).where(User.role == "admin", User.is_active.is_(True))
    if exclude_id is not None:
        stmt = stmt.where(User.id != exclude_id)
    return await db.scalar(stmt)


@router.patch("/users/{user_id}/role", response_model=UserOut)
async def change_role(user_id: uuid.UUID, body: RoleIn, request: Request, admin: AdminUser, db: DbSession):
    if body.role not in ("admin", "user"):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail="role must be user|admin")
    user = await db.get(User, user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="User not found")
    # Don't let the platform lose its last admin (no recovery path: invite-only + setup self-locks).
    # Lock the invariant before the count so concurrent demotions can't both slip through.
    if user.role == "admin" and body.role == "user":
        await _lock_admin_invariant(db)
        if await _active_admin_count(db, exclude_id=user.id) == 0:
            raise HTTPException(status.HTTP_409_CONFLICT, detail="Cannot demote the last admin")
    user.role = body.role
    await write_audit(db, action="user_role_change", actor_id=admin.id, target_type="user",
                      target_id=str(user.id), ip=client_ip(request), metadata={"role": body.role})
    await db.commit()
    return await _user_out(db, user)


@router.post("/users/{user_id}/deactivate", response_model=UserOut)
async def deactivate_user(user_id: uuid.UUID, request: Request, admin: AdminUser, db: DbSession):
    user = await db.get(User, user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="User not found")
    if user.id == admin.id:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="You cannot deactivate yourself")
    if user.role == "admin":
        await _lock_admin_invariant(db)
        if await _active_admin_count(db, exclude_id=user.id) == 0:
            raise HTTPException(status.HTTP_409_CONFLICT, detail="Cannot deactivate the last admin")
    user.is_active = False
    await revoke_all_for_user(db, user.id)
    await write_audit(db, action="user_deactivate", actor_id=admin.id, target_type="user",
                      target_id=str(user.id), ip=client_ip(request))
    await db.commit()
    return await _user_out(db, user)


@router.post("/users/{user_id}/activate", response_model=UserOut)
async def activate_user(user_id: uuid.UUID, request: Request, admin: AdminUser, db: DbSession):
    user = await db.get(User, user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="User not found")
    user.is_active = True
    await write_audit(db, action="user_activate", actor_id=admin.id, target_type="user",
                      target_id=str(user.id), ip=client_ip(request))
    await db.commit()
    return await _user_out(db, user)


class TeamOut(BaseModel):
    id: str
    name: str
    slug: str
    is_default: bool
    member_count: int


class TeamCreateIn(BaseModel):
    name: str = Field(max_length=120)  # teams.name is String(120); route strips + checks non-empty


class TeamRenameIn(BaseModel):
    name: str = Field(max_length=120)


class MemberIn(BaseModel):
    user_id: uuid.UUID


def _slugify(name: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", name.strip().lower()).strip("-")
    return s or "team"


async def _unique_slug(db: AsyncSession, base: str, *, exclude_id: uuid.UUID | None = None) -> str:
    """A team slug unique across teams (teams.slug is UNIQUE). Two distinct names can slugify to
    the same base (e.g. 'Dev Team' / 'dev-team'); without this they'd trip the constraint and
    500. Appends -2, -3, … on collision. The route still catches IntegrityError as a race
    backstop, but this resolves the common case cleanly."""
    candidate = base
    n = 1
    while True:
        stmt = select(Team.id).where(Team.slug == candidate)
        if exclude_id is not None:
            stmt = stmt.where(Team.id != exclude_id)
        if await db.scalar(stmt) is None:
            return candidate
        n += 1
        candidate = f"{base}-{n}"


_TEAM_NAME_CONFLICT = "A team with this name already exists"


async def _validated_name_and_slug(
    db: AsyncSession, raw_name: str, *, exclude_id: uuid.UUID | None = None
) -> tuple[str, str]:
    """Shared create/rename validation: strip + blank -> 422, name clash -> 409,
    then a collision-free slug. Callers keep their IntegrityError -> 409 race backstop."""
    name = raw_name.strip()
    if not name:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail="name is required")
    clash_stmt = select(Team).where(Team.name == name)
    if exclude_id is not None:
        clash_stmt = clash_stmt.where(Team.id != exclude_id)
    if await db.scalar(clash_stmt) is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=_TEAM_NAME_CONFLICT)
    return name, await _unique_slug(db, _slugify(name), exclude_id=exclude_id)


async def _team_out(db: AsyncSession, team: Team) -> TeamOut:
    count = await db.scalar(
        select(func.count()).select_from(TeamMember).where(TeamMember.team_id == team.id)
    )
    return TeamOut(id=str(team.id), name=team.name, slug=team.slug,
                   is_default=team.is_default, member_count=count)


@router.get("/teams", response_model=list[TeamOut])
async def list_teams(admin: AdminUser, db: DbSession):
    teams = (await db.execute(select(Team).order_by(Team.name))).scalars().all()
    return [await _team_out(db, t) for t in teams]


@router.post("/teams", status_code=201, response_model=TeamOut)
async def create_team(body: TeamCreateIn, request: Request, admin: AdminUser, db: DbSession):
    name, slug = await _validated_name_and_slug(db, body.name)
    team = Team(name=name, slug=slug, is_default=False, created_by=admin.id)
    db.add(team)
    try:
        await db.flush()  # backstop for a name/slug uniqueness race -> clean 409, never a 500
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, detail=_TEAM_NAME_CONFLICT)
    await write_audit(db, action="team_create", actor_id=admin.id, target_type="team",
                      target_id=str(team.id), ip=client_ip(request), metadata={"name": name})
    await db.commit()
    return await _team_out(db, team)


@router.patch("/teams/{team_id}", response_model=TeamOut)
async def rename_team(team_id: uuid.UUID, body: TeamRenameIn, request: Request, admin: AdminUser, db: DbSession):
    team = await db.get(Team, team_id)
    if team is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Team not found")
    # Slug kept consistent with the renamed team (it was previously left stale), collision-safe.
    name, slug = await _validated_name_and_slug(db, body.name, exclude_id=team_id)
    team.name = name
    team.slug = slug
    try:
        await db.flush()  # name/slug uniqueness race backstop -> 409, never 500
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, detail=_TEAM_NAME_CONFLICT)
    await write_audit(db, action="team_rename", actor_id=admin.id, target_type="team",
                      target_id=str(team.id), ip=client_ip(request), metadata={"name": name})
    await db.commit()
    return await _team_out(db, team)


@router.post("/teams/{team_id}/members", status_code=204)
async def add_team_member(team_id: uuid.UUID, body: MemberIn, request: Request, admin: AdminUser, db: DbSession):
    team = await db.get(Team, team_id)
    user = await db.get(User, body.user_id)
    if team is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Team not found")
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="User not found")
    try:
        added = await add_member(db, team_id, user.id)
    except IntegrityError:
        # a concurrent add won the membership race (ADD1) — idempotent end state, no error/audit
        await db.rollback()
        return
    if added:
        await write_audit(db, action="membership_add", actor_id=admin.id, target_type="team",
                          target_id=str(team_id), ip=client_ip(request), metadata={"user_id": str(body.user_id)})
    await db.commit()


@router.delete("/teams/{team_id}/members/{user_id}", status_code=204)
async def remove_team_member(team_id: uuid.UUID, user_id: uuid.UUID, request: Request, admin: AdminUser, db: DbSession):
    try:
        await remove_member(db, team_id, user_id)
    except LastTeamError:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="Cannot remove a user's last team")
    await write_audit(db, action="membership_remove", actor_id=admin.id, target_type="team",
                      target_id=str(team_id), ip=client_ip(request), metadata={"user_id": str(user_id)})
    await db.commit()


@router.delete("/teams/{team_id}", status_code=204)
async def delete_team_route(team_id: uuid.UUID, request: Request, admin: AdminUser, db: DbSession):
    team = await db.get(Team, team_id)
    if team is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Team not found")
    try:
        await delete_team(db, team)
    except DefaultTeamError:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="Cannot delete the default team")
    except LastTeamError:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="Deleting this team would orphan a member")
    await write_audit(db, action="team_delete", actor_id=admin.id, target_type="team",
                      target_id=str(team_id), ip=client_ip(request))
    await db.commit()
