from __future__ import annotations

from fastapi import Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import MeOut, build_me
from app.api.http_utils import client_ip, session_max_age, set_session_cookie
from app.core.clock import utcnow
from app.models import User
from app.services.audit import write_audit
from app.services.sessions import create_session


async def complete_login(
    db: AsyncSession,
    request: Request,
    response: Response,
    user: User,
    *,
    remember: bool,
    audit_action: str,
    stamp_last_login: bool = True,
    audit_target_type: str | None = None,
    audit_target_id: str | None = None,
) -> MeOut:
    """Shared login-completion tail: stamp last_login_at, create session, audit,
    commit, set session cookie, return the /me payload.

    `stamp_last_login=False` for flows where account creation IS the entry (setup wizard,
    invite accept) — those never recorded a last_login_at on their first session.
    """
    if stamp_last_login:
        user.last_login_at = utcnow()
    sess = await create_session(
        db, user_id=user.id, ip=client_ip(request),
        user_agent=request.headers.get("user-agent"), remember=remember,
    )
    await write_audit(
        db, action=audit_action, actor_id=user.id,
        target_type=audit_target_type, target_id=audit_target_id,
        ip=client_ip(request),
    )
    await db.commit()
    set_session_cookie(response, sess.id, session_max_age(remember))
    return await build_me(db, user)
