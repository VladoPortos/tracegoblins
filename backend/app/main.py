from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI, Response, status
from sqlalchemy import text

from app.core.config import settings, validate_runtime_secrets
from app.db.session import SessionLocal, engine
from app.scheduler import start_scheduler, stop_scheduler


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Fail fast before serving if a production deployment is misconfigured (placeholder
    # SECRET_KEY / missing TOKEN_ENC_KEY). No-op outside environment='production'.
    validate_runtime_secrets(settings)
    # M4: in-process APScheduler. start_scheduler() is a no-op unless this worker wins
    # the Postgres leader lock AND settings.scheduler_enabled is True (tests set it false).
    await start_scheduler()
    try:
        yield
    finally:
        await stop_scheduler()
        await engine.dispose()


def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.app_name,
        lifespan=lifespan,
        docs_url="/api/docs" if settings.environment != "production" else None,
        # Disable the OpenAPI schema endpoint in production too (mirrors docs_url): a security-
        # first, internet-facing app shouldn't disclose its full API surface unauthenticated.
        # The SPA build generates its client from a dev server / scripts/export_openapi.py.
        openapi_url="/api/openapi.json" if settings.environment != "production" else None,
    )

    meta = APIRouter(prefix="/api", tags=["meta"])

    @meta.get("/health")
    async def health(response: Response) -> dict[str, str]:
        db_ok = "ok"
        try:
            async with SessionLocal() as session:
                await session.execute(text("SELECT 1"))
        except Exception:
            db_ok = "error"
            # 503 so the Docker HEALTHCHECK (curl -fsS) actually fails when the DB is
            # unreachable, instead of reporting the container healthy with a dead database.
            response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return {"status": "ok" if db_ok == "ok" else "error", "db": db_ok}

    app.include_router(meta)

    # A password-policy violation is a client error, not a 500 (AUTH1) — map it to 422 with the
    # human-readable reason at every call site (setup wizard / invite-accept / change-password).
    from app.security.passwords import PasswordPolicyError

    @app.exception_handler(PasswordPolicyError)
    async def _password_policy(_request, exc: PasswordPolicyError) -> Response:
        from fastapi.responses import JSONResponse
        return JSONResponse(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                            content={"detail": str(exc)})

    from app.api import (
        admin, analytics, annotations, auth, comments, controllers, invites, kb,
        mfa, notifications, projects, runs, setup, users,
    )

    app.include_router(setup.router)
    app.include_router(auth.router)
    app.include_router(mfa.router)  # M7 2FA
    app.include_router(mfa.login_verify_router)  # M7 two-step login verify
    app.include_router(invites.admin_router)
    app.include_router(invites.public_router)
    app.include_router(admin.router)
    app.include_router(runs.router)  # M2
    app.include_router(projects.router)  # M2 Projects subsystem
    app.include_router(users.router)  # M3
    app.include_router(annotations.router)  # M3 Phase B
    app.include_router(comments.router)  # M3 Phase B
    app.include_router(notifications.router)  # M3 Phase C
    app.include_router(controllers.router)  # M4 Phase E
    app.include_router(kb.router)  # M5 Phase D
    app.include_router(analytics.router)  # per-template failure analytics

    from app.static import mount_spa

    mount_spa(app, settings.app_static_dir)

    from app.security.csrf import CSRFMiddleware
    from app.security.headers import SecurityHeadersMiddleware

    app.add_middleware(CSRFMiddleware)  # inner
    app.add_middleware(SecurityHeadersMiddleware, report_only=settings.csp_report_only)  # outermost
    return app


app = create_app()
