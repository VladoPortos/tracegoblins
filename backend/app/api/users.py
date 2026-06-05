from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi import status
from pydantic import BaseModel
from sqlalchemy import delete, or_, select

from app.api.deps import AdminUser, CurrentUser, DbSession, require_password_current
from app.api.http_utils import client_ip
from app.models import MfaRecoveryCode, TeamMember, User
from app.services.audit import write_audit
from app.services.sessions import revoke_all_for_user

router = APIRouter(prefix="/api/users", tags=["users"])


class DirectoryUser(BaseModel):
    id: str
    display_name: str
    email: str


@router.get("", response_model=list[DirectoryUser])
async def search_users(
    user: CurrentUser, db: DbSession,
    q: str = Query(..., min_length=1),          # q required, min length 1 -> else 422
    limit: int = Query(20, ge=1, le=50),
):
    # Active users who share >= 1 team with the requester, excluding the requester.
    # NOT run-visibility-gated (spec §5) — this is the share-modal directory.
    my_teams = select(TeamMember.team_id).where(TeamMember.user_id == user.id)
    shared_team_user_ids = select(TeamMember.user_id).where(TeamMember.team_id.in_(my_teams))
    like = f"%{q}%"
    rows = (await db.execute(
        select(User)
        .where(
            User.id.in_(shared_team_user_ids),
            User.id != user.id,
            User.is_active.is_(True),
            or_(User.display_name.ilike(like), User.email.ilike(like)),
        )
        .order_by(User.display_name)
        .limit(limit)
    )).scalars().all()
    return [
        DirectoryUser(id=str(u.id), display_name=u.display_name, email=u.email)
        for u in rows
    ]


@router.post(
    "/{user_id}/reset-2fa",
    status_code=204,
    dependencies=[Depends(require_password_current)],  # same forced-change gate as /api/admin/*
)
async def reset_2fa(user_id: uuid.UUID, request: Request, db: DbSession, admin: AdminUser):
    target = await db.get(User, user_id)
    if target is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="User not found")
    target.totp_enabled = False
    target.totp_secret = None
    target.totp_confirmed_at = None
    target.totp_last_used_step = None
    await db.execute(delete(MfaRecoveryCode).where(MfaRecoveryCode.user_id == target.id))
    # Incident response: revoke the target's existing sessions so an attacker who already holds
    # one can't persist past the 2FA reset — they must re-authenticate (and re-enroll).
    await revoke_all_for_user(db, target.id)
    await write_audit(db, action="mfa_admin_reset", actor_id=admin.id,
                      target_type="user", target_id=str(target.id), ip=client_ip(request))
    await db.commit()
