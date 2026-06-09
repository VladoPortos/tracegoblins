from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Cookie, HTTPException, Request, Response, status
from pydantic import BaseModel

from app.api.deps import CurrentUser, DbSession
from app.core.config import settings
from app.api.http_utils import (
    MFA_PENDING_COOKIE,
    clear_pending_cookie,
    client_ip,
    session_max_age,
    set_session_cookie,
)
from app.core.crypto import decrypt_token, encrypt_token
from app.models import User
from app.security import totp
from app.security.cookies import unsign_pending_id
from app.security.ratelimit import mfa_verify_limiter
from app.services.audit import write_audit
from app.services.mfa import consume_recovery_code, issue_recovery_codes
from app.services.pending_login import consume_pending, get_valid_pending
from app.services.sessions import create_session

router = APIRouter(prefix="/api/auth/2fa", tags=["mfa"])


class SetupOut(BaseModel):
    secret: str
    otpauth_uri: str
    qr_svg: str


class CodeIn(BaseModel):
    code: str


class RecoveryOut(BaseModel):
    recovery_codes: list[str]


@router.post("/setup", response_model=SetupOut)
async def setup(request: Request, user: CurrentUser, db: DbSession):
    # SECURITY: never re-initialize TOTP while it is already enabled. Otherwise a hijacked
    # session could call /setup to overwrite the secret and flip totp_enabled→False, silently
    # DISABLING 2FA without the current code that /disable requires (an MFA-downgrade bypass).
    # Re-enrolling must go through /disable (which demands a valid code) first.
    if user.totp_enabled:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="2FA already enabled; disable it first")
    secret = totp.generate_secret()
    user.totp_secret = encrypt_token(secret)   # stored encrypted, NOT yet enabled
    user.totp_enabled = False
    await write_audit(db, action="mfa_setup_initiated", actor_id=user.id, ip=client_ip(request))
    await db.commit()
    uri = totp.otpauth_uri(secret, email=user.email)
    return SetupOut(secret=secret, otpauth_uri=uri, qr_svg=totp.qr_svg(uri))


def _active_secret(user) -> str:
    if not user.totp_secret:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="No TOTP setup in progress")
    return decrypt_token(user.totp_secret)


@router.post("/enable", response_model=RecoveryOut)
async def enable(data: CodeIn, request: Request, user: CurrentUser, db: DbSession):
    secret = _active_secret(user)
    step = totp.verify_totp(secret, data.code)
    if step is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Invalid code")
    user.totp_enabled = True
    user.totp_confirmed_at = datetime.now(timezone.utc)
    # Burn the enrollment code's timestep into the replay guard so it can't be reused at the
    # very next login within its ±30s window (NIST SP 800-63B: consume the confirmation OTP).
    user.totp_last_used_step = step
    codes = await issue_recovery_codes(db, user, n=10)
    await write_audit(db, action="mfa_enabled", actor_id=user.id, ip=client_ip(request))
    await db.commit()
    return RecoveryOut(recovery_codes=codes)


def _mfa_mgmt_keys(request: Request, user) -> tuple[str, str]:
    """Rate-limit keys for the authenticated 2FA-management surface (disable / regenerate).

    BOTH keys are 'mfa-mgmt' namespaced so this surface is fully independent of the
    pre-session login-verify budget — its per-IP and per-user keys must not collide with
    login_verify's ('mfa-verify-ip:'/'mfa:'), or a few failed management attempts would lock
    out 2FA *login* for every user sharing the NAT/IP. It keeps the same brute-force ceiling
    (a session-only attacker still cannot grind the 6-digit code to remove 2FA or mint codes)."""
    ip = client_ip(request)
    return (f"mfa-mgmt-ip:{ip or 'unknown'}", f"mfa-mgmt:{user.id}")


@router.post("/disable", status_code=204)
async def disable(data: CodeIn, request: Request, user: CurrentUser, db: DbSession):
    if not user.totp_enabled:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="2FA is not enabled")
    keys = _mfa_mgmt_keys(request, user)
    decision = await mfa_verify_limiter.check(*keys)
    if not decision.allowed:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many attempts. Try again later.",
            headers={"Retry-After": str(decision.retry_after)},
        )
    secret = _active_secret(user)
    ok = totp.verify_totp(secret, data.code) is not None or await consume_recovery_code(db, user, data.code)
    if not ok:
        await mfa_verify_limiter.record_failure(*keys)
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Invalid code")
    await mfa_verify_limiter.reset(*keys)
    user.totp_secret = None
    user.totp_enabled = False
    user.totp_confirmed_at = None
    user.totp_last_used_step = None
    await issue_recovery_codes(db, user, n=0)  # clears the set
    await write_audit(db, action="mfa_disabled", actor_id=user.id, ip=client_ip(request))
    await db.commit()


@router.post("/recovery-codes/regenerate", response_model=RecoveryOut)
async def regenerate(data: CodeIn, request: Request, user: CurrentUser, db: DbSession):
    if not user.totp_enabled:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="2FA is not enabled")
    keys = _mfa_mgmt_keys(request, user)
    decision = await mfa_verify_limiter.check(*keys)
    if not decision.allowed:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many attempts. Try again later.",
            headers={"Retry-After": str(decision.retry_after)},
        )
    if totp.verify_totp(_active_secret(user), data.code) is None:
        await mfa_verify_limiter.record_failure(*keys)
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Invalid code")
    await mfa_verify_limiter.reset(*keys)
    codes = await issue_recovery_codes(db, user, n=10)
    await write_audit(db, action="mfa_recovery_regenerated", actor_id=user.id, ip=client_ip(request))
    await db.commit()
    return RecoveryOut(recovery_codes=codes)


# ---------------------------------------------------------------------------
# Pre-session verify route — no CurrentUser dependency (called before session)
# ---------------------------------------------------------------------------

login_verify_router = APIRouter(prefix="/api/auth/login", tags=["mfa"])


@login_verify_router.post("/verify")
async def login_verify(
    data: CodeIn,
    request: Request,
    response: Response,
    db: DbSession,
    tg_mfa_pending: Annotated[str | None, Cookie(alias=MFA_PENDING_COOKIE)] = None,
):
    bad = HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired login")
    if not tg_mfa_pending:
        raise bad
    # Enforce the TTL cryptographically too (defense-in-depth); the DB expires_at remains the
    # authoritative gate, but a stale signed cookie is rejected before any DB work.
    pid = unsign_pending_id(tg_mfa_pending, max_age_seconds=settings.mfa_pending_ttl_minutes * 60)
    if pid is None:
        raise bad
    pending = await get_valid_pending(db, pid)
    if pending is None:
        clear_pending_cookie(response)
        raise bad

    ip = client_ip(request)
    # 'mfa-verify-ip:' namespace keeps this pre-session login budget separate from the
    # authenticated mgmt surface (_mfa_mgmt_keys) so neither can lock/reset the other's IP key.
    keys = (f"mfa-verify-ip:{ip or 'unknown'}", f"mfa:{pending.user_id}")
    decision = await mfa_verify_limiter.check(*keys)
    if not decision.allowed:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many attempts. Try again later.",
            headers={"Retry-After": str(decision.retry_after)},
        )

    # Lock the user row FOR UPDATE so the replay-guard read→compare→write of
    # totp_last_used_step is serialized. Two *distinct* pending-login rows for the same user
    # lock different pending rows (no mutual exclusion there), so without this the same TOTP
    # step could validate twice under a race; the user-row lock closes that window.
    user = await db.get(User, pending.user_id, with_for_update=True)
    if user is None or not user.is_active or not user.totp_enabled or not user.totp_secret:
        raise bad

    secret = decrypt_token(user.totp_secret)
    step = totp.verify_totp(secret, data.code)
    used_recovery = False
    if step is not None and (user.totp_last_used_step is None or step > user.totp_last_used_step):
        user.totp_last_used_step = step  # replay guard
        ok = True
    elif step is None and await consume_recovery_code(db, user, data.code):
        ok, used_recovery = True, True
    else:
        ok = False

    if not ok:
        await mfa_verify_limiter.record_failure(*keys)
        await write_audit(db, action="mfa_verify_failed", actor_id=user.id, ip=ip)
        await db.commit()
        raise bad

    await mfa_verify_limiter.reset(*keys)
    await consume_pending(db, pending)
    user.last_login_at = datetime.now(timezone.utc)  # login completes only after the 2nd factor
    sess = await create_session(
        db, user_id=user.id, ip=ip,
        user_agent=request.headers.get("user-agent"),
        remember=pending.remember,
    )
    await write_audit(
        db,
        action="login" if not used_recovery else "mfa_recovery_used",
        actor_id=user.id,
        ip=ip,
    )
    await db.commit()
    clear_pending_cookie(response)
    set_session_cookie(response, sess.id, session_max_age(pending.remember))
    from app.api.auth import build_me
    return await build_me(db, user)
