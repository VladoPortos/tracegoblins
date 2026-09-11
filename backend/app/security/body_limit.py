from __future__ import annotations

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send


class _RequestBodyTooLarge(Exception):
    pass


class RequestBodyLimitMiddleware:
    """Reject oversized HTTP bodies before framework-level body parsing."""

    def __init__(
        self,
        app: ASGIApp,
        *,
        default_max_bytes: int,
        run_max_bytes: int,
        project_upload_max_bytes: int,
    ) -> None:
        self.app = app
        self.default_max_bytes = default_max_bytes
        self.run_max_bytes = run_max_bytes
        self.project_upload_max_bytes = project_upload_max_bytes

    def _limit_for(self, scope: Scope) -> int:
        path = scope.get("path", "")
        method = scope.get("method", "").upper()
        if method == "POST" and path == "/api/runs":
            return self.run_max_bytes
        if (
            method == "POST"
            and path.startswith("/api/projects/")
            and path.endswith("/uploads")
        ):
            return self.project_upload_max_bytes
        return self.default_max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        limit = self._limit_for(scope)
        headers = {name.lower(): value for name, value in scope.get("headers", [])}
        raw_length = headers.get(b"content-length")
        if raw_length is not None:
            try:
                if int(raw_length) > limit:
                    await self._reject(scope, receive, send)
                    return
            except ValueError:
                # Let the HTTP server/framework handle malformed Content-Length syntax.
                pass

        received = 0
        response_started = False

        async def limited_receive() -> Message:
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > limit:
                    raise _RequestBodyTooLarge
            return message

        async def tracked_send(message: Message) -> None:
            nonlocal response_started
            if message["type"] == "http.response.start":
                response_started = True
            await send(message)

        try:
            await self.app(scope, limited_receive, tracked_send)
        except _RequestBodyTooLarge:
            if response_started:
                raise
            await self._reject(scope, receive, send)

    @staticmethod
    async def _reject(scope: Scope, receive: Receive, send: Send) -> None:
        response = JSONResponse(
            status_code=413,
            content={"detail": "Request body too large"},
        )
        await response(scope, receive, send)
