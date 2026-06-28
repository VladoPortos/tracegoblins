from __future__ import annotations

import hashlib
import logging
import uuid

from datetime import timedelta

from sqlalchemy import and_, or_, select

from app.awx.sync import _engine_of, release_controller_lock, try_acquire_controller_lock
from app.core.clock import utcnow
from app.core.config import settings
from app.core.crypto import decrypt_token
from app.db.session import SessionLocal
from app.models import Project
from app.projects.git import clone_or_fetch, is_clonable_git_url
from app.projects.storage import project_repo_path

logger = logging.getLogger(__name__)

_PROJ_LOCK_NAMESPACE = 0x50524F4A  # "PROJ" — distinct from the AWX5 controller namespace


def project_lock_key(project_id: uuid.UUID | str) -> int:
    """Stable signed 64-bit advisory-lock key from the project uuid (project-namespaced)."""
    h = hashlib.blake2b(str(project_id).encode(), digest_size=8).digest()
    return int.from_bytes(h, "big", signed=True) ^ _PROJ_LOCK_NAMESPACE


async def run_clone(project_id: str) -> None:
    """Clone or fetch one project's git source under a per-project advisory lock.

    Fresh SessionLocal() (not a request session). The lock rides a DEDICATED connection (never
    committed/cycled) so the per-status commits can't drop it — same pattern as the controller
    sync lock. status: pending/error → cloning → cloned | error.

    Short-circuits BEFORE acquiring the lock on non-https URL or scm_type != git so a bad
    config doesn't hold a lock slot at all.
    """
    async with SessionLocal() as db:
        project = await db.get(Project, uuid.UUID(project_id))
        if project is None:
            return

        if project.scm_type != "git":
            project.status = "error"
            project.last_clone_error = "Only scm_type='git' projects can be cloned"
            project.last_clone_at = utcnow()
            await db.commit()
            return

        effective_url = project.git_url_override or project.scm_url
        if not is_clonable_git_url(effective_url):
            project.status = "error"
            project.last_clone_error = (
                "Effective git URL is not https — set an https URL override "
                "(SSH and non-https schemes are unsupported)"
            )
            project.last_clone_at = utcnow()
            await db.commit()
            return

        key = project_lock_key(project.id)
        # Dedicated lock connection: opened from the engine, held for the clone's lifetime,
        # never committed/cycled. The lock is session-level on THIS backend — commits on `db`
        # can't cycle the pool and drop it.
        lock_conn = await _engine_of(db).connect()
        try:
            acquired = await try_acquire_controller_lock(lock_conn, key)
        except Exception:
            await lock_conn.close()
            raise
        if not acquired:
            await lock_conn.close()
            return  # another clone/fetch for this project is already in flight

        try:
            project.status = "cloning"
            project.last_clone_error = None
            await db.commit()

            secret = (
                decrypt_token(project.git_secret_encrypted)
                if project.git_secret_encrypted else None
            )
            size, _branch = await clone_or_fetch(
                effective_url, project_repo_path(project.id),
                auth_type=project.git_auth_type or "none",
                username=project.git_username,
                secret=secret,
                max_bytes=settings.git_clone_max_bytes,
                timeout=settings.git_clone_timeout_seconds,
            )
            project.status = "cloned"
            project.clone_size_bytes = size
            project.last_clone_at = utcnow()
            project.last_clone_error = None
            await db.commit()
        except Exception as e:
            logger.exception("clone failed for project %s", project_id)
            await db.rollback()
            await db.refresh(project)
            project.status = "error"
            project.last_clone_error = str(e)[:1000]
            project.last_clone_at = utcnow()
            await db.commit()
        finally:
            # Always release on the dedicated lock connection; never through `db`.
            await release_controller_lock(lock_conn, key)
            await lock_conn.close()


# A pending/cloning project untouched for this long is treated as orphaned by a crashed worker and
# retried (REL1); an actively-running clone bumps updated_at well within the window, and the
# per-project advisory lock dedupes anyway, so a live clone is never double-fired.
_STALE_CLONE_MINUTES = 15


async def _projects_to_refetch(db) -> list[uuid.UUID]:
    """Cloned projects (routine refresh) PLUS pending/cloning projects orphaned by a crash (REL1)."""
    stale_before = utcnow() - timedelta(minutes=_STALE_CLONE_MINUTES)
    return list((await db.scalars(
        select(Project.id).where(
            or_(Project.status == "cloned",
                and_(Project.status.in_(("pending", "cloning")),
                     Project.updated_at < stale_before))
        )
    )).all())


async def refetch_cloned_projects() -> None:
    """Periodic job: fetch updates for every already-cloned project so revisions referenced by
    newly-synced runs become browsable, AND retry projects left in pending/cloning by a crashed
    worker (REL1). Each project re-uses run_clone (which fetches when the bare repo already exists).
    Per-project errors are swallowed so one bad project cannot abort the rest of the sweep."""
    async with SessionLocal() as db:
        ids = await _projects_to_refetch(db)
    for pid in ids:
        try:
            await run_clone(str(pid))
        except Exception:
            logger.exception("periodic re-fetch failed for project %s", pid)
