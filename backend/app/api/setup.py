from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, Response, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import func, select, text

from app.api.auth import MeOut
from app.api.deps import DbSession
from app.api.http_utils import client_ip
from app.api.login_flow import complete_login
from app.models import Team, TeamMember, User
from app.security.passwords import hash_password, validate_password
from app.security.ratelimit import setup_limiter, too_many_attempts

router = APIRouter(prefix="/api/setup", tags=["setup"])

_SETUP_LOCK_KEY = 728001  # arbitrary constant for pg_advisory_xact_lock


class SetupIn(BaseModel):
    email: EmailStr
    display_name: str = Field(min_length=1, max_length=120)  # matches users.display_name String(120)
    password: str = Field(max_length=1024)                   # bound argon2 input (validate_password floors length)


async def _user_count(db) -> int:
    return await db.scalar(select(func.count()).select_from(User))


class SetupStatusOut(BaseModel):
    needs_setup: bool


@router.get("/status", response_model=SetupStatusOut)
async def setup_status(db: DbSession) -> SetupStatusOut:
    return SetupStatusOut(needs_setup=(await _user_count(db)) == 0)


@router.post("", status_code=201, response_model=MeOut)
async def run_setup(data: SetupIn, request: Request, response: Response, db: DbSession):
    # Throttle this unauthenticated, CSRF-exempt window (race-to-create-admin + argon2 DoS guard).
    ip = client_ip(request)
    decision = await setup_limiter.check(f"setup:{ip or 'unknown'}")
    if not decision.allowed:
        raise too_many_attempts(decision)
    await setup_limiter.record_failure(f"setup:{ip or 'unknown'}")
    # Serialize concurrent setup attempts; advisory xact lock auto-releases at txn end.
    # (Under the savepoint test harness the lock is held until the outer rollback, so true
    # concurrency is verified by the separate db_per_test race test — keep that test.)
    await db.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": _SETUP_LOCK_KEY})
    if (await _user_count(db)) != 0:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="Setup already completed")

    validate_password(data.password)
    admin = User(
        email=data.email,
        display_name=data.display_name,
        password_hash=hash_password(data.password),
        role="admin",
        is_active=True,
        must_change_password=False,
    )
    db.add(admin)
    await db.flush()

    general = Team(name="General", slug="general", is_default=True, created_by=admin.id)
    db.add(general)
    await db.flush()
    db.add(TeamMember(team_id=general.id, user_id=admin.id))

    # stamp_last_login=False: the wizard never recorded a last_login_at for the first admin.
    return await complete_login(
        db, request, response, admin, remember=False,
        audit_action="setup_complete", stamp_last_login=False,
    )
