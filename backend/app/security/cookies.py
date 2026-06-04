from __future__ import annotations

from itsdangerous import BadSignature, URLSafeTimedSerializer

from app.core.config import settings

_SALT = "tg-session-cookie-v1"


def _serializer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(settings.secret, salt=_SALT)


def sign_session_id(session_id: str) -> str:
    return _serializer().dumps(session_id)


def unsign_session_id(cookie_value: str, max_age_seconds: int | None = None) -> str | None:
    """Return the session id, or None if forged/tampered/too old.

    The DB session row remains the source of truth for revocation + real expiry.
    """
    try:
        return _serializer().loads(cookie_value, max_age=max_age_seconds)
    except BadSignature:  # also catches SignatureExpired (subclass) + BadData
        return None


_PENDING_SALT = "tg-mfa-pending-v1"


def _pending_serializer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(settings.secret, salt=_PENDING_SALT)


def sign_pending_id(pending_id: str) -> str:
    return _pending_serializer().dumps(pending_id)


def unsign_pending_id(cookie_value: str, max_age_seconds: int | None = None) -> str | None:
    try:
        return _pending_serializer().loads(cookie_value, max_age=max_age_seconds)
    except BadSignature:
        return None
