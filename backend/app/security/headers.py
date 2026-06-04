from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.types import ASGIApp

# style-src needs 'unsafe-inline' because the ported design system renders via React
# inline style objects on nearly every element. script-src stays strict 'self' (Vite
# bundles JS, no inline <script>). font-src 'self' = self-hosted IBM Plex woff2.
_CSP = (
    "default-src 'self'; "
    "script-src 'self'; "
    "style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data:; "
    "font-src 'self'; "
    "connect-src 'self'; "
    "object-src 'none'; "
    "base-uri 'self'; "
    "form-action 'self'; "
    "frame-ancestors 'none'"
)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: ASGIApp, *, report_only: bool = False) -> None:
        super().__init__(app)
        self._csp_header = (
            "Content-Security-Policy-Report-Only" if report_only else "Content-Security-Policy"
        )

    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        h = response.headers
        h[self._csp_header] = _CSP
        h["X-Frame-Options"] = "DENY"
        h["X-Content-Type-Options"] = "nosniff"
        h["Referrer-Policy"] = "strict-origin-when-cross-origin"
        h["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        h["Cross-Origin-Opener-Policy"] = "same-origin"
        h["Cross-Origin-Resource-Policy"] = "same-origin"
        # HSTS intentionally NOT set — owned by the TLS-terminating reverse proxy.
        return response
