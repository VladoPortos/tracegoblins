import hmac
import secrets

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.types import ASGIApp

from app.core.config import settings

SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS", "TRACE"})
# Only the first-run wizard is exempt: it runs on an empty DB before any cookie exists,
# is rate-limited, and self-locks once an admin exists.
CSRF_EXEMPT_PREFIXES: tuple[str, ...] = ("/api/setup",)


def _new_token() -> str:
    return secrets.token_urlsafe(32)


class CSRFMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)
        self.cookie_name = settings.csrf_cookie_name
        self.header_name = settings.csrf_header_name
        self.secure = settings.cookie_secure
        self.samesite = settings.cookie_samesite

    def _is_exempt(self, path: str) -> bool:
        return any(path.startswith(p) for p in CSRF_EXEMPT_PREFIXES)

    async def dispatch(self, request: Request, call_next):
        method = request.method.upper()
        cookie_token = request.cookies.get(self.cookie_name)

        if method not in SAFE_METHODS and not self._is_exempt(request.url.path):
            header_token = request.headers.get(self.header_name)
            if not cookie_token or not header_token or not hmac.compare_digest(cookie_token, header_token):
                return JSONResponse({"detail": "CSRF token missing or invalid"}, status_code=403)

        response: Response = await call_next(request)

        if not cookie_token:
            response.set_cookie(
                key=self.cookie_name,
                value=_new_token(),
                max_age=60 * 60 * 12,
                secure=self.secure,
                httponly=False,  # MUST be JS-readable for double-submit
                samesite=self.samesite,
                path="/",
            )
        return response
