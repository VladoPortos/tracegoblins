from __future__ import annotations

from fastapi import Request, Response

from app.core.config import settings
from app.security.cookies import sign_pending_id, sign_session_id


def client_ip(request: Request) -> str | None:
    # uvicorn --forwarded-allow-ips has already rewritten this from X-Forwarded-For.
    return request.client.host if request.client else None


def is_secure(request: Request) -> bool:
    return settings.cookie_secure


def session_max_age(remember: bool) -> int:
    return (
        settings.session_remember_days * 86400
        if remember
        else settings.session_absolute_hours * 3600
    )


def set_session_cookie(request: Request, response: Response, session_id: str, max_age: int) -> None:
    response.set_cookie(
        key=settings.session_cookie_name,
        value=sign_session_id(session_id),
        max_age=max_age,
        httponly=True,
        secure=is_secure(request),
        samesite=settings.cookie_samesite,
        path="/",
    )


def clear_session_cookie(response: Response) -> None:
    # Match the attributes the cookie was set with so the deletion is consistent on the proxy.
    response.delete_cookie(
        settings.session_cookie_name, path="/",
        secure=settings.cookie_secure, httponly=True, samesite=settings.cookie_samesite,
    )


MFA_PENDING_COOKIE = "tg_mfa_pending"


def set_pending_cookie(request: Request, response: Response, pending_id: str) -> None:
    response.set_cookie(
        key=MFA_PENDING_COOKIE,
        value=sign_pending_id(pending_id),
        max_age=settings.mfa_pending_ttl_minutes * 60,
        httponly=True,
        secure=is_secure(request),
        samesite=settings.cookie_samesite,
        path="/",
    )


def clear_pending_cookie(response: Response) -> None:
    response.delete_cookie(
        MFA_PENDING_COOKIE, path="/",
        secure=settings.cookie_secure, httponly=True, samesite=settings.cookie_samesite,
    )
