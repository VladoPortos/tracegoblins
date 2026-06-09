from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, Response, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import func, select, text

from app.api.auth import MeOut, build_me
from app.api.deps import DbSession
from app.api.http_utils import client_ip, session_max_age, set_session_cookie
from app.models import Team, TeamMember, User
from app.security.passwords import hash_password, validate_password
from app.security.ratelimit import setup_limiter
from app.services.audit import write_audit
from app.services.sessions import create_session

router = APIRouter(prefix="/api/setup", tags=["setup"])

_SETUP_LOCK_KEY = 728001  # arbitrary constant for pg_advisory_xact_lock


class SetupIn(BaseModel):
    email: EmailStr
    display_name: str = Field(min_length=1, max_length=120)  # matches users.display_name String(120)
    password: str = Field(max_length=1024)                   # bound argon2 input (validate_password floors length)


async def _user_count(db) -> int:
    return await db.scalar(select(func.count()).select_from(User))


@router.get("/status")
async def setup_status(db: DbSession) -> dict[str, bool]:
    return {"needs_setup": (await _user_count(db)) == 0}


@router.post("", status_code=status.HTTP_201_CREATED, response_model=MeOut)
async def run_setup(data: SetupIn, request: Request, response: Response, db: DbSession):
    # Throttle this unauthenticated, CSRF-exempt window (race-to-create-admin + argon2 DoS guard).
    ip = client_ip(request)
    decision = await setup_limiter.check(f"setup:{ip or 'unknown'}")
    if not decision.allowed:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS, detail="Too many attempts. Try again later.",
            headers={"Retry-After": str(decision.retry_after)},
        )
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

    sess = await create_session(
        db, user_id=admin.id, ip=client_ip(request),
        user_agent=request.headers.get("user-agent"), remember=False,
    )
    await write_audit(db, action="setup_complete", actor_id=admin.id, ip=client_ip(request))
    await db.commit()
    set_session_cookie(response, sess.id, session_max_age(False))
    return await build_me(db, admin)
