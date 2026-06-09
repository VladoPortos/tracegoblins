from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Request, Response, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, EmailStr
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, DbSession
from app.core.config import settings
from app.api.http_utils import clear_session_cookie, client_ip, session_max_age, set_session_cookie
from app.models import Team, TeamMember, User
from app.security.passwords import hash_password, needs_rehash, validate_password, verify_password
from app.security.ratelimit import login_limiter
from app.services.audit import write_audit
from app.services.sessions import create_session, revoke_all_for_user, revoke_session

router = APIRouter(prefix="/api/auth", tags=["auth"])


class TeamBrief(BaseModel):
    id: str
    name: str
    slug: str
    is_default: bool


class MeOut(BaseModel):
    id: str
    email: str
    display_name: str
    role: str
    initials: str | None = None
    avatar_color: str | None = None
    must_change_password: bool
    totp_enabled: bool = False
    mfa_setup_required: bool = False
    teams: list[TeamBrief]


async def build_me(db: AsyncSession, user: User) -> MeOut:
    teams = (
        await db.execute(
            select(Team)
            .join(TeamMember, TeamMember.team_id == Team.id)
            .where(TeamMember.user_id == user.id)
            .order_by(Team.name)
        )
    ).scalars().all()
    return MeOut(
        id=str(user.id),
        email=user.email,
        display_name=user.display_name,
        role=user.role,
        initials=user.initials,
        avatar_color=user.avatar_color,
        must_change_password=user.must_change_password,
        totp_enabled=user.totp_enabled,
        mfa_setup_required=(settings.mfa_admin_required and user.role == "admin" and not user.totp_enabled),
        teams=[TeamBrief(id=str(t.id), name=t.name, slug=t.slug, is_default=t.is_default) for t in teams],
    )


# Precomputed once so a missing user still pays argon2 verify cost (no enumeration oracle).
_DUMMY_HASH = hash_password("tg-dummy-password-for-constant-time-verify")


class LoginIn(BaseModel):
    email: EmailStr
    password: str
    remember: bool = False


@router.get("/csrf")
async def csrf_bootstrap() -> dict[str, bool]:
    # The CSRF middleware (Task 9) sets the csrf cookie on this safe response.
    return {"ok": True}


@router.post("/login")
async def login(data: LoginIn, request: Request, response: Response, db: DbSession):
    ip = client_ip(request)
    ip_key = f"ip:{ip or 'unknown'}"
    # casefold() (Unicode-aware) + strip() so case/whitespace variants of one CITEXT email
    # can't each get a fresh per-account budget.
    acct_key = f"acct:{data.email.strip().casefold()}"

    decision = await login_limiter.check(ip_key, acct_key)
    if not decision.allowed:
        await write_audit(db, action="login_locked", ip=ip, metadata={"email": data.email})
        await db.commit()
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many attempts. Try again later.",
            headers={"Retry-After": str(decision.retry_after)},
        )

    user = await db.scalar(select(User).where(User.email == data.email))
    if user is None:
        verify_password(_DUMMY_HASH, data.password)  # constant-time-ish
        ok = False
    else:
        pw_ok = verify_password(user.password_hash, data.password)  # always pay argon2 cost
        ok = pw_ok and user.is_active

    if not ok:
        await login_limiter.record_failure(ip_key, acct_key)
        await write_audit(db, action="login_failed", ip=ip, metadata={"email": data.email})
        await db.commit()
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password")

    await login_limiter.reset(ip_key, acct_key)
    if needs_rehash(user.password_hash):
        user.password_hash = hash_password(data.password)

    if user.totp_enabled:
        # Do NOT stamp last_login_at here — the login isn't complete until the second factor
        # is verified (login_verify stamps it on success). Otherwise an abandoned/failed 2FA
        # attempt would record a successful-looking login time.
        from app.api.http_utils import set_pending_cookie
        from app.services.pending_login import create_pending
        pending = await create_pending(
            db, user_id=user.id, remember=data.remember, ip=ip,
            user_agent=request.headers.get("user-agent"),
        )
        await write_audit(db, action="login_mfa_required", actor_id=user.id, ip=ip)
        await db.commit()
        # JSONResponse is the actual response object; set the cookie directly on it so
        # httpx sees it (FastAPI only merges the injected `response` headers for dict/model
        # returns, not when the route returns a Response subclass directly).
        jr = JSONResponse({"mfa_required": True})
        set_pending_cookie(jr, str(pending.id))
        return jr

    # No 2FA: the password IS the completed login — stamp last_login_at now. (Python datetime,
    # not func.now(): with expire_on_commit=False the attribute isn't re-expired after commit.)
    user.last_login_at = datetime.now(timezone.utc)
    sess = await create_session(
        db, user_id=user.id, ip=ip, user_agent=request.headers.get("user-agent"), remember=data.remember
    )
    await write_audit(db, action="login", actor_id=user.id, ip=ip)
    await db.commit()
    set_session_cookie(response, sess.id, session_max_age(data.remember))
    return await build_me(db, user)


@router.get("/me", response_model=MeOut)
async def me(user: CurrentUser, db: DbSession) -> MeOut:
    return await build_me(db, user)


@router.post("/logout", status_code=204)
async def logout(request: Request, response: Response, db: DbSession, user: CurrentUser):
    await revoke_session(db, request.state.session_id)
    await write_audit(db, action="logout", actor_id=user.id, ip=client_ip(request))
    await db.commit()
    clear_session_cookie(response)


@router.post("/logout-everywhere", status_code=204)
async def logout_everywhere(request: Request, response: Response, db: DbSession, user: CurrentUser):
    await revoke_all_for_user(db, user.id)
    await write_audit(db, action="logout_everywhere", actor_id=user.id, ip=client_ip(request))
    await db.commit()
    clear_session_cookie(response)


class ChangePasswordIn(BaseModel):
    current_password: str
    new_password: str


@router.post("/change-password", status_code=204)
async def change_password(data: ChangePasswordIn, request: Request, db: DbSession, user: CurrentUser):
    if not verify_password(user.password_hash, data.current_password):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Current password is incorrect")
    validate_password(data.new_password)
    user.password_hash = hash_password(data.new_password)
    user.must_change_password = False
    await revoke_all_for_user(db, user.id, except_session_id=request.state.session_id)
    await write_audit(db, action="password_change", actor_id=user.id, ip=client_ip(request))
    await db.commit()
