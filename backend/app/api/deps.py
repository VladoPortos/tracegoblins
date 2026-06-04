from __future__ import annotations

from typing import Annotated

from fastapi import Cookie, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.session import get_db
from app.models import User
from app.security.cookies import unsign_session_id
from app.services.sessions import get_valid_session, touch_session

DbSession = Annotated[AsyncSession, Depends(get_db)]


async def current_user(
    request: Request,
    db: DbSession,
    tg_session: Annotated[str | None, Cookie(alias=settings.session_cookie_name)] = None,
) -> User:
    unauthorized = HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    if not tg_session:
        raise unauthorized
    session_id = unsign_session_id(tg_session)
    if session_id is None:
        raise unauthorized
    sess = await get_valid_session(db, session_id)
    if sess is None:
        raise unauthorized
    user = await db.get(User, sess.user_id)
    if user is None or not user.is_active:
        raise unauthorized
    await touch_session(db, sess)
    request.state.session_id = sess.id
    return user


CurrentUser = Annotated[User, Depends(current_user)]


async def require_admin(user: CurrentUser) -> User:
    if user.role != "admin":
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Admin required")
    return user


AdminUser = Annotated[User, Depends(require_admin)]


async def require_password_current(user: CurrentUser) -> User:
    if user.must_change_password:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, detail={"code": "password_change_required"}
        )
    return user


GatedUser = Annotated[User, Depends(require_password_current)]
