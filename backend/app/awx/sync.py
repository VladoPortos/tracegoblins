# app/awx/sync.py
from __future__ import annotations

import hashlib
import logging
import uuid
from dataclasses import dataclass

from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession

from app.awx.client import AwxClient, AwxError
from app.awx.projects_sync import sync_projects
from app.core.clock import parse_iso as _parse_iso, utcnow
from app.core.crypto import TokenCryptoError, decrypt_token
from app.kb.service import match_run
from app.logparser import build_tree
from app.logparser.job_events import parse_job_events
from app.models import AwxController, Run, RunRaw
from app.services.audit import write_audit
from app.services.ingestion import build_run_from_parsed
from app.services.run_tree import apply_job_detail, build_run_nodes

logger = logging.getLogger(__name__)

_LOCK_NAMESPACE = 0x41575835  # "AWX5"
_TERMINAL_STATUSES = frozenset({"successful", "failed", "error", "canceled"})
# Cap the stored raw log for one AWX run. Concatenated job-event stdout is otherwise
# unbounded; a single huge/hostile job could bloat the DB and the /raw API payload. 16M chars
# is generous (≈2× the 8 MB manual-upload cap) — real logs sit well under it.
MAX_RUNRAW_CHARS = 16_000_000


def _join_stdout_capped(events: list[dict]) -> str:
    """Concatenate per-event stdout, bounded by MAX_RUNRAW_CHARS (truncation is marked)."""
    parts: list[str] = []
    size = 0
    truncated = False
    for ev in events:
        s = ev.get("stdout") or ""
        if not s:
            continue
        parts.append(s)
        size += len(s)
        if size >= MAX_RUNRAW_CHARS:
            truncated = True
            break
    content = "".join(parts)
    if truncated:
        content = content[:MAX_RUNRAW_CHARS] + "\n…[truncated: raw log exceeded storage cap]\n"
    return content


def controller_lock_key(controller_id: uuid.UUID | str) -> int:
    """Stable signed 64-bit advisory-lock key from the controller uuid (namespaced)."""
    h = hashlib.blake2b(str(controller_id).encode(), digest_size=8).digest()
    return int.from_bytes(h, "big", signed=True) ^ _LOCK_NAMESPACE


def _engine_of(db: AsyncSession):
    """The AsyncEngine backing this Session, for opening the dedicated lock connection.
    Use `db.bind` (the ASYNC bind), NOT `db.get_bind()` (which returns the *sync* Engine/
    Connection). In prod the Session is bound to the AsyncEngine; in the savepoint test
    fixture it's bound to an AsyncConnection, so fall back to that connection's `.engine`.
    Either way we open a SEPARATE connection so the lock never rides the per-job-committing
    persistence connection."""
    bind = db.bind  # AsyncEngine (engine-bound) or AsyncConnection (savepoint fixture)
    return bind.engine if isinstance(bind, AsyncConnection) else bind


async def try_acquire_controller_lock(conn: AsyncConnection, key: int) -> bool:
    """SESSION-level pg_try_advisory_lock on a DEDICATED connection — non-blocking; False if
    a sync already holds it. The lock is bound to the backend CONNECTION (not the SQLAlchemy
    Session), and sync_controller commits once per job, so the lock MUST live on its own
    connection that never commits/cycles — otherwise a pooled-connection rotation would
    silently drop it and the finally-release would unlock a different backend."""
    return bool(await conn.scalar(text("SELECT pg_try_advisory_lock(:k)").bindparams(k=key)))


async def release_controller_lock(conn: AsyncConnection, key: int) -> None:
    await conn.execute(text("SELECT pg_advisory_unlock(:k)").bindparams(k=key))


@dataclass
class SyncResult:
    controller_id: str
    status: str  # 'ok' | 'error' | 'skipped_locked'
    imported: int
    skipped: int
    last_synced_job_id: int | None
    error: str | None = None


def _abs_url(base: str, rel: str | None) -> str | None:
    """Join an AWX-relative path onto base_url; pass through absolute urls; None -> None."""
    if rel is None:
        return None
    if rel.startswith(("http://", "https://")):
        return rel
    return f"{base.rstrip('/')}/{rel.lstrip('/')}"


async def sync_controller(db: AsyncSession, controller: AwxController) -> SyncResult:
    """Pull finished AWX jobs since the controller cursor into Run/Task/RunRaw rows.

    One transaction per job (durable, resumable cursor). Holds the per-controller advisory
    lock on a DEDICATED connection (separate from the per-job-committing `db` Session) for
    the whole sync, so a manual sync and a scheduled sync never overlap and the per-job
    commits can't cycle the pooled connection and drop the lock.
    """
    key = controller_lock_key(controller.id)
    # Dedicated lock connection: opened from the engine, held for the sync's lifetime, never
    # committed/cycled. It is the ONLY thing the advisory lock rides on.
    lock_conn = await _engine_of(db).connect()
    try:
        acquired = await try_acquire_controller_lock(lock_conn, key)
    except Exception:
        await lock_conn.close()
        raise
    if not acquired:
        await lock_conn.close()
        return SyncResult(
            controller_id=str(controller.id), status="skipped_locked",
            imported=0, skipped=0, last_synced_job_id=controller.last_synced_job_id,
        )
    imported = 0
    skipped = 0
    since = controller.last_synced_job_id or 0
    max_id = controller.last_synced_job_id or 0
    pending_floor: int | None = None  # lowest non-terminal job id seen this sync

    def _durable_cursor() -> int:
        """Cursor to persist: never advance to/past a skipped non-terminal job (so it is
        actually re-listed next sync instead of being leapfrogged by a higher-id terminal job),
        and never rewind below the previous cursor (retention + resumability need forward-only)."""
        if pending_floor is None:
            return max_id
        return max(since, min(max_id, pending_floor - 1))

    try:
        controller.last_sync_status = "running"
        controller.sync_total = None
        controller.sync_done = 0
        controller.sync_current_job = None
        await db.commit()  # committed so the UI sees "running"

        token = decrypt_token(controller.auth_token_encrypted)
        async with AwxClient(controller.base_url, token, controller.verify_ssl) as client:
            async for job in client.list_jobs(since):
                if controller.sync_total is None:
                    controller.sync_total = getattr(client, "last_list_count", None)
                controller.sync_current_job = str(job.id)

                # Belt-and-suspenders: skip any job that is not in a terminal state
                # (successful/failed/error/canceled). AWX rarely returns non-terminal
                # jobs through a finished-filter query, but a 'new' job with no events
                # could slip through. Record it as the cursor floor so the persisted cursor is
                # held below this id (see _durable_cursor) — otherwise a higher-id terminal job
                # later in this ascending window would advance the cursor past it and it would be
                # permanently lost instead of re-evaluated on the next sync.
                if job.status not in _TERMINAL_STATUSES:
                    pending_floor = job.id if pending_floor is None else min(pending_floor, job.id)
                    controller.sync_done = (controller.sync_done or 0) + 1
                    await db.commit()
                    continue

                # dedupe by (controller_id, awx_job_id)
                exists = await db.scalar(
                    select(Run.id).where(
                        Run.controller_id == controller.id,
                        Run.awx_job_id == str(job.id),
                    ).limit(1)
                )
                if exists is not None:
                    skipped += 1
                    max_id = max(max_id, job.id)
                    controller.sync_done = (controller.sync_done or 0) + 1
                    await db.commit()
                    continue

                events = await client.get_job_events(job.id)
                parsed = parse_job_events(events)
                tree = build_tree(events)
                detail = await client.get_job_detail(job.id)

                run, tasks = build_run_from_parsed(
                    parsed,
                    source="awx",
                    owner_user_id=None,
                    team_id=None,
                    template_name=job.name,
                    awx_user=job.created_by_username,
                    log_time=_parse_iso(job.finished),
                    awx_job_status=job.status,
                    controller_id=controller.id,
                    awx_job_id=str(job.id),
                    awx_job_url=_abs_url(controller.base_url, job.url),
                    awx_organization_id=job.organization_id,
                    awx_organization_name=job.organization_name,
                    awx_launch_type=job.launch_type,
                    awx_workflow_name=job.workflow_name,
                )
                run.elapsed = job.elapsed  # float seconds from AWX; None when AWX omits it
                run.launched_at = _parse_iso(job.started)  # AWX launch time; None if AWX omits it
                try:
                    db.add(run)
                    await db.flush()  # assign run.id (may trip the unique constraint here)
                    for t in tasks:
                        t.run_id = run.id
                    db.add_all(tasks)
                    apply_job_detail(run, detail)
                    nodes, node_results = build_run_nodes(tree, run.id)
                    db.add_all(nodes)
                    db.add_all(node_results)
                    db.add(RunRaw(run_id=run.id, content=_join_stdout_capped(events)))
                    await db.commit()
                except IntegrityError:
                    # A concurrent insert already wrote this (controller_id, awx_job_id) and
                    # hit uq_runs_controller_id_awx_job_id -> dedupe. The conflict can surface
                    # at the flush (row already durably visible) OR at commit (deferred), so the
                    # whole persistence block is guarded. The rollback expires `controller`;
                    # refresh it before any later write.
                    await db.rollback()
                    await db.refresh(controller)
                    skipped += 1
                    max_id = max(max_id, job.id)
                    controller.sync_done = (controller.sync_done or 0) + 1
                    await db.commit()
                    continue
                imported += 1
                max_id = max(max_id, job.id)

                # durable per-job cursor -> sync is resumable after a crash/timeout
                controller.last_synced_job_id = _durable_cursor()
                controller.sync_done = (controller.sync_done or 0) + 1
                await db.commit()

                # Best-effort KB matching, AFTER the per-job commit. Must NOT raise:
                # a matcher error cannot abort the sync loop or roll back the imported job.
                try:
                    await match_run(db, run)
                except Exception:
                    logger.exception("kb match_run failed for awx run %s", run.id)

            # Best-effort AWX project-metadata mirror, piggybacked on the run sync. A failure
            # here MUST NOT abort the run sync or roll back imported jobs — it commits its own
            # work. Run inside the open client (one cheap extra paginated call).
            try:
                await sync_projects(db, controller, client)
                await db.refresh(controller)  # sync_projects committed → refresh before later writes
            except Exception:
                logger.exception("sync_projects failed for controller %s", controller.id)
                await db.rollback()
                await db.refresh(controller)

        final_cursor = _durable_cursor()
        controller.last_synced_job_id = final_cursor
        controller.last_sync_status = "ok"
        controller.last_sync_at = utcnow()
        controller.last_sync_error = None
        controller.status = "connected"
        controller.sync_total = None
        controller.sync_done = None
        controller.sync_current_job = None
        await write_audit(
            db, action="awx_sync",
            target_type="awx_controller", target_id=str(controller.id),
            metadata={"imported": imported, "skipped": skipped,
                      "last_synced_job_id": final_cursor},
        )
        await db.commit()
        return SyncResult(
            controller_id=str(controller.id), status="ok",
            imported=imported, skipped=skipped, last_synced_job_id=final_cursor,
        )
    except (AwxError, TokenCryptoError) as e:
        # The in-flight job txn is rolled back; refresh `controller` (expired by the rollback)
        # before stamping the error status so we don't write through a stale instance.
        await db.rollback()
        await db.refresh(controller)
        controller.last_sync_status = "error"
        controller.last_sync_error = str(e)[:1000]
        controller.status = "error"
        controller.last_sync_at = utcnow()
        controller.sync_total = None
        controller.sync_done = None
        controller.sync_current_job = None
        await db.commit()
        return SyncResult(
            controller_id=str(controller.id), status="error",
            imported=imported, skipped=skipped, last_synced_job_id=max_id, error=str(e),
        )
    except Exception as e:
        # Any UNEXPECTED failure (parser / DB / runtime) must NOT leave the controller pinned
        # at last_sync_status="running" — that pins manual sync at a permanent 409 (M4-D10) and
        # only an auto-mode controller could ever self-heal. Reset to 'error', log the
        # traceback, and return an error result (consistent with the AwxError path above).
        logger.exception("unexpected error during sync of controller %s", controller.id)
        try:
            await db.rollback()
            await db.refresh(controller)
            controller.last_sync_status = "error"
            controller.last_sync_error = f"Unexpected sync failure: {type(e).__name__}"[:1000]
            controller.status = "error"
            controller.last_sync_at = utcnow()
            controller.sync_total = None
            controller.sync_done = None
            controller.sync_current_job = None
            await db.commit()
        except Exception:
            # Don't let a failure while recording the error status mask the original error.
            logger.exception("failed to record error status for controller %s", controller.id)
        return SyncResult(
            controller_id=str(controller.id), status="error",
            imported=imported, skipped=skipped, last_synced_job_id=max_id, error=str(e),
        )
    finally:
        # Release on the dedicated lock connection (the lock rode this backend the whole time)
        # and close it. Never released through `db` — that would target the wrong connection.
        await release_controller_lock(lock_conn, key)
        await lock_conn.close()
