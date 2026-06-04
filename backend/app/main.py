from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI
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
        openapi_url="/api/openapi.json",
    )

    meta = APIRouter(prefix="/api", tags=["meta"])

    @meta.get("/health")
    async def health() -> dict[str, str]:
        db_ok = "ok"
        try:
            async with SessionLocal() as session:
                await session.execute(text("SELECT 1"))
        except Exception:
            db_ok = "error"
        return {"status": "ok", "db": db_ok}

    app.include_router(meta)
    from app.api import (
        admin, annotations, auth, comments, controllers, invites, kb,
        mfa, notifications, runs, setup, users,
    )

    app.include_router(setup.router)
    app.include_router(auth.router)
    app.include_router(mfa.router)  # M7 2FA
    app.include_router(mfa.login_verify_router)  # M7 two-step login verify
    app.include_router(invites.admin_router)
    app.include_router(invites.public_router)
    app.include_router(admin.router)
    app.include_router(runs.router)  # M2
    app.include_router(users.router)  # M3
    app.include_router(annotations.router)  # M3 Phase B
    app.include_router(comments.router)  # M3 Phase B
    app.include_router(notifications.router)  # M3 Phase C
    app.include_router(controllers.router)  # M4 Phase E
    app.include_router(kb.router)  # M5 Phase D

    from app.static import mount_spa

    mount_spa(app, settings.app_static_dir)

    from app.security.csrf import CSRFMiddleware
    from app.security.headers import SecurityHeadersMiddleware

    app.add_middleware(CSRFMiddleware)  # inner
    app.add_middleware(SecurityHeadersMiddleware, report_only=settings.csp_report_only)  # outermost
    return app


app = create_app()
