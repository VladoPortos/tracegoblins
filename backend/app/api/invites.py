from __future__ import annotations

import hashlib
import secrets
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select

from app.api.auth import MeOut, build_me
from app.api.deps import AdminUser, DbSession, require_password_current
from app.api.http_utils import client_ip, session_max_age, set_session_cookie
from app.core.config import settings
from app.models import Invite, Team, TeamMember, User
from app.security.passwords import hash_password, validate_password
from app.services.audit import write_audit
from app.services.sessions import create_session

admin_router = APIRouter(
    prefix="/api/admin", tags=["invites"], dependencies=[Depends(require_password_current)]
)
public_router = APIRouter(prefix="/api/invites", tags=["invites"])


def _hash_token(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


async def _load_valid_invite(db, token: str, *, for_update: bool = False) -> Invite | None:
    stmt = select(Invite).where(Invite.token_hash == _hash_token(token))
    if for_update:
        stmt = stmt.with_for_update()  # row-lock so accept stays single-use under concurrency
    invite = await db.scalar(stmt)
    now = datetime.now(timezone.utc)
    if invite is None or invite.accepted_at is not None or now >= invite.expires_at:
        return None
    return invite


class InviteCreateIn(BaseModel):
    email: EmailStr
    role: str = "user"
    team_ids: list[str] = Field(default=[], max_length=100)


@admin_router.post("/invites", status_code=status.HTTP_201_CREATED)
async def create_invite(data: InviteCreateIn, request: Request, admin: AdminUser, db: DbSession):
    if data.role not in ("user", "admin"):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail="role must be user|admin")
    # Validate target teams up front: each must parse as a UUID and exist (else 422),
    # so a bad id can't FK-crash invite acceptance later.
    team_uuids: list[str] = []
    for t in data.team_ids:
        try:
            tid = uuid.UUID(t)
        except (ValueError, TypeError):
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail=f"invalid team id: {t}")
        if await db.get(Team, tid) is None:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail=f"unknown team: {t}")
        team_uuids.append(str(tid))
    raw = secrets.token_urlsafe(32)
    invite = Invite(
        email=data.email,
        token_hash=_hash_token(raw),
        target_role=data.role,
        target_team_ids=team_uuids,
        invited_by=admin.id,
        expires_at=datetime.now(timezone.utc) + timedelta(hours=settings.invite_expire_hours),
    )
    db.add(invite)
    await write_audit(db, action="user_invite", actor_id=admin.id, target_type="invite",
                      target_id=str(invite.id), ip=client_ip(request), metadata={"email": data.email})
    await db.commit()
    base = str(request.base_url).rstrip("/")
    return {
        "link": f"{base}/invite/{raw}",
        "expires_at": invite.expires_at.isoformat(),
    }


@public_router.get("/{token}")
async def get_invite(token: str, db: DbSession):
    invite = await _load_valid_invite(db, token)
    if invite is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Invalid or expired invite")
    return {"email": invite.email, "valid": True}


class InviteAcceptIn(BaseModel):
    display_name: str = Field(min_length=1, max_length=120)  # matches users.display_name String(120)
    password: str = Field(max_length=1024)


@public_router.post("/{token}/accept", status_code=status.HTTP_201_CREATED, response_model=MeOut)
async def accept_invite(
    token: str, data: InviteAcceptIn, request: Request, response: Response, db: DbSession
):
    invite = await _load_valid_invite(db, token, for_update=True)
    if invite is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Invalid or expired invite")
    if await db.scalar(select(User).where(User.email == invite.email)) is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="A user with this email already exists")

    validate_password(data.password)
    user = User(
        email=invite.email,
        display_name=data.display_name,
        password_hash=hash_password(data.password),
        role=invite.target_role,
        is_active=True,
        must_change_password=False,
    )
    db.add(user)
    await db.flush()

    # Defensive: keep only teams that still exist (one may have been deleted post-invite),
    # and guard the UUID parse — the General auto-join preserves the >=1-team invariant.
    target_ids: set[uuid.UUID] = set()
    for t in (invite.target_team_ids or []):
        try:
            tid = uuid.UUID(t)
        except (ValueError, TypeError):
            continue
        if await db.get(Team, tid) is not None:
            target_ids.add(tid)
    general = await db.scalar(select(Team).where(Team.is_default.is_(True)))
    if general is not None:
        target_ids.add(general.id)
    for tid in target_ids:
        db.add(TeamMember(team_id=tid, user_id=user.id))

    invite.accepted_at = datetime.now(timezone.utc)
    sess = await create_session(
        db, user_id=user.id, ip=client_ip(request),
        user_agent=request.headers.get("user-agent"), remember=False,
    )
    await write_audit(db, action="invite_accept", actor_id=user.id, target_type="user",
                      target_id=str(user.id), ip=client_ip(request))
    await db.commit()
    set_session_cookie(response, sess.id, session_max_age(False))
    return await build_me(db, user)
