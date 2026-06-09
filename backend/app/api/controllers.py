from __future__ import annotations

import uuid

from fastapi import (
    APIRouter, BackgroundTasks, Depends, HTTPException, Request, status,
)
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.api.controllers_schemas import (
    ControllerCreate,
    ControllerOut,
    ControllerUpdate,
    SyncStartedOut,
    TestConnectionIn,
    TestConnectionOut,
)
from app.api.deps import AdminUser, CurrentUser, DbSession, require_password_current
from app.api.http_utils import client_ip
from app.api.validation import resolve_team_or_422
from app.awx.client import AwxClient, AwxError
from app.awx.sync import sync_controller
from app.core.crypto import decrypt_token, encrypt_token
from app.db.session import SessionLocal
from app.models import AwxController, ControllerTeam
from app.scheduler import reconcile_controller
from app.security.urls import is_http_url
from app.services.audit import write_audit
from app.services.controllers_query import controller_to_out
from app.services.visibility import my_team_ids

router = APIRouter(
    prefix="/api/controllers",
    tags=["controllers"],
    dependencies=[Depends(require_password_current)],
)


async def _assigned_team_ids(db: DbSession, controller_id: uuid.UUID) -> set[uuid.UUID]:
    return set((await db.execute(
        select(ControllerTeam.team_id).where(ControllerTeam.controller_id == controller_id)
    )).scalars().all())


async def _controller_or_404(db: DbSession, controller_id: uuid.UUID) -> AwxController:
    controller = await db.get(AwxController, controller_id)
    if controller is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Controller not found")
    return controller


@router.get("", response_model=list[ControllerOut])
async def list_controllers(user: CurrentUser, db: DbSession):
    if user.role == "admin":
        rows = (await db.execute(
            select(AwxController).order_by(AwxController.created_at)
        )).scalars().all()
        return [await controller_to_out(db, c) for c in rows]

    team_ids = await my_team_ids(db, user)
    if not team_ids:
        return []
    rows = (await db.execute(
        select(AwxController)
        .where(AwxController.id.in_(
            select(ControllerTeam.controller_id).where(ControllerTeam.team_id.in_(team_ids))
        ))
        .order_by(AwxController.created_at)
    )).scalars().all()
    # Non-admin: redact the token mask and filter assignments to the viewer's own teams so a
    # member can't enumerate other teams' names/ids/org scopes or read token metadata (H6).
    return [await controller_to_out(db, c, viewer_team_ids=team_ids) for c in rows]


def _validate_sync(sync_mode: str, interval: int | None) -> None:
    if sync_mode == "auto" and (interval is None or interval <= 0):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="sync_interval_minutes is required and must be > 0 when sync_mode='auto'",
        )


async def _apply_assignments(db: DbSession, controller_id: uuid.UUID, assignments) -> None:
    """Insert ControllerTeam rows; a dup (either partial unique index) -> 409.

    Atomicity: in-memory dedupe FIRST (so a dup within the SAME request is a clean 422 that
    never touches the DB), then each insert flushes inside a SAVEPOINT (db.begin_nested) so a
    DB-level dup raises 409 WITHOUT tearing down the controller insert/edit already in this
    unit of work. A bare rollback would discard the controller row too — the savepoint scopes
    the undo to just the failed assignment."""
    seen: set[tuple[uuid.UUID, int | None]] = set()
    for a in assignments:
        # resolve-then-dedupe is order-equivalent to the old dedupe-then-exists: a pair can
        # only be in `seen` after its first occurrence already passed the exists check.
        tid = (await resolve_team_or_422(db, a.team_id)).id
        if (tid, a.awx_organization_id) in seen:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT,
                                detail="Duplicate team/org assignment in request")
        seen.add((tid, a.awx_organization_id))
        try:
            async with db.begin_nested():  # SAVEPOINT: scopes any dup rollback to this row only
                db.add(ControllerTeam(
                    controller_id=controller_id, team_id=tid,
                    awx_organization_id=a.awx_organization_id,
                ))
                await db.flush()
        except IntegrityError:
            raise HTTPException(
                status.HTTP_409_CONFLICT, detail="Duplicate team/org assignment",
            )


@router.post("", status_code=201, response_model=ControllerOut)
async def create_controller(
    payload: ControllerCreate, request: Request, db: DbSession, user: AdminUser,
):
    if not is_http_url(payload.base_url):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT,
                            detail="base_url must be an http(s) URL")
    _validate_sync(payload.sync_mode, payload.sync_interval_minutes)

    controller = AwxController(
        name=payload.name,
        base_url=payload.base_url.strip(),
        auth_token_encrypted=encrypt_token(payload.token),
        verify_ssl=payload.verify_ssl,
        sync_mode=payload.sync_mode,
        sync_interval_minutes=payload.sync_interval_minutes,
        created_by_user_id=user.id,
    )
    db.add(controller)
    try:
        await db.flush()  # surfaces the unique name violation
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, detail="A controller with that name exists")

    try:
        await _apply_assignments(db, controller.id, payload.team_assignments)
    except HTTPException:
        # Atomic: a rejected assignment (dup/unknown/invalid) discards the WHOLE unit of work
        # — including the controller insert flushed above — so nothing partial persists.
        await db.rollback()
        raise

    await write_audit(db, action="controller_create", actor_id=user.id,
                      target_type="awx_controller", target_id=str(controller.id),
                      ip=client_ip(request))
    await db.commit()
    reconcile_controller(
        str(controller.id), sync_mode=controller.sync_mode,
        sync_interval_minutes=controller.sync_interval_minutes,
    )
    return await controller_to_out(db, controller)


@router.delete("/{controller_id}", status_code=204)
async def delete_controller(
    controller_id: uuid.UUID, request: Request, db: DbSession, user: AdminUser,
):
    controller = await _controller_or_404(db, controller_id)
    await db.delete(controller)  # cascades controller_teams + synced runs (FK ON DELETE CASCADE)
    await write_audit(db, action="controller_delete", actor_id=user.id,
                      target_type="awx_controller", target_id=str(controller_id),
                      ip=client_ip(request))
    await db.commit()
    reconcile_controller(str(controller_id), sync_mode="manual",
                         sync_interval_minutes=None, deleted=True)
    return None


@router.patch("/{controller_id}", response_model=ControllerOut)
async def update_controller(
    controller_id: uuid.UUID, payload: ControllerUpdate,
    request: Request, db: DbSession, user: AdminUser,
):
    controller = await _controller_or_404(db, controller_id)

    if payload.base_url is not None:
        if not is_http_url(payload.base_url):
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT,
                                detail="base_url must be an http(s) URL")
        controller.base_url = payload.base_url.strip()
    if payload.name is not None:
        controller.name = payload.name
    if payload.verify_ssl is not None:
        controller.verify_ssl = payload.verify_ssl

    eff_mode = payload.sync_mode if payload.sync_mode is not None else controller.sync_mode
    eff_interval = (
        payload.sync_interval_minutes
        if payload.sync_interval_minutes is not None
        else controller.sync_interval_minutes
    )
    _validate_sync(eff_mode, eff_interval)
    controller.sync_mode = eff_mode
    controller.sync_interval_minutes = eff_interval

    token_rotated = False
    if payload.token is not None:
        controller.auth_token_encrypted = encrypt_token(payload.token)
        token_rotated = True

    try:
        await db.flush()  # name unique clash
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, detail="A controller with that name exists")

    if payload.team_assignments is not None:
        await db.execute(
            ControllerTeam.__table__.delete().where(
                ControllerTeam.controller_id == controller.id
            )
        )
        await db.flush()
        try:
            await _apply_assignments(db, controller.id, payload.team_assignments)
        except HTTPException:
            # A rejected reassignment discards the whole edit (incl. the cleared/changed rows).
            await db.rollback()
            raise

    await write_audit(db, action="controller_update", actor_id=user.id,
                      target_type="awx_controller", target_id=str(controller.id),
                      ip=client_ip(request), metadata={"token_rotated": token_rotated})
    await db.commit()
    reconcile_controller(
        str(controller.id), sync_mode=controller.sync_mode,
        sync_interval_minutes=controller.sync_interval_minutes,
    )
    return await controller_to_out(db, controller)


@router.post("/test", response_model=TestConnectionOut)
async def test_connection_adhoc(
    payload: TestConnectionIn, request: Request, db: DbSession, user: AdminUser,
):
    """Ad-hoc connection test BEFORE a controller is saved (the add modal calls this).
    Unlike the per-controller variant there is no record to fall back on, so base_url
    and token must be supplied in the payload. The token is used in-memory only and is
    never persisted by this path."""
    base_url = payload.base_url or ""
    if not is_http_url(base_url):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT,
                            detail="base_url must be an http(s) URL")
    if not payload.token:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT,
                            detail="token is required for an ad-hoc connection test")
    verify_ssl = payload.verify_ssl if payload.verify_ssl is not None else True

    await write_audit(db, action="controller_test", actor_id=user.id,
                      target_type="awx_controller", target_id=None,
                      ip=client_ip(request))
    await db.commit()
    try:
        async with AwxClient(base_url, payload.token, verify_ssl) as awx:
            ping = await awx.ping()
        return TestConnectionOut(ok=True, version=ping.get("version"),
                                 identity=ping.get("identity"))
    except AwxError as e:
        return TestConnectionOut(ok=False, error=str(e))


@router.post("/{controller_id}/test", response_model=TestConnectionOut)
async def test_connection(
    controller_id: uuid.UUID, payload: TestConnectionIn,
    request: Request, db: DbSession, user: AdminUser,
):
    controller = await _controller_or_404(db, controller_id)

    base_url = payload.base_url if payload.base_url is not None else controller.base_url
    # SSRF guard: an ad-hoc base_url must be http(s) with a netloc — same check create/update use.
    if not is_http_url(base_url):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT,
                            detail="base_url must be an http(s) URL")
    verify_ssl = payload.verify_ssl if payload.verify_ssl is not None else controller.verify_ssl
    token = (
        payload.token if payload.token is not None
        else decrypt_token(controller.auth_token_encrypted)
    )

    await write_audit(db, action="controller_test", actor_id=user.id,
                      target_type="awx_controller", target_id=str(controller_id),
                      ip=client_ip(request))
    await db.commit()
    try:
        async with AwxClient(base_url, token, verify_ssl) as awx:
            ping = await awx.ping()
        return TestConnectionOut(ok=True, version=ping.get("version"),
                                 identity=ping.get("identity"))
    except AwxError as e:
        return TestConnectionOut(ok=False, error=str(e))


async def _run_manual_sync(controller_id: str) -> None:
    """Background entrypoint: a fresh SessionLocal() (NOT the request session) loads the
    controller and runs sync_controller, which takes the per-controller advisory lock and
    skips cleanly (status='skipped_locked') if an auto-sync is already running."""
    async with SessionLocal() as db:
        controller = await db.get(AwxController, uuid.UUID(controller_id))
        if controller is None:
            return
        await sync_controller(db, controller)


@router.post("/{controller_id}/sync", status_code=202, response_model=SyncStartedOut)
async def sync_now(
    controller_id: uuid.UUID, background: BackgroundTasks,
    request: Request, db: DbSession, user: CurrentUser,
):
    """Launch a manual sync. The 409 'already running' pre-check below is BEST-EFFORT (it
    races a sync that flips last_sync_status between this read and the launch); the real
    guard is the per-controller advisory lock inside sync_controller, so a racing duplicate
    launch is simply dropped as status='skipped_locked' and still returns 202. The 409 just
    gives a fast, friendly answer in the common case."""
    controller = await _controller_or_404(db, controller_id)

    assigned = await _assigned_team_ids(db, controller_id)
    mine = await my_team_ids(db, user)
    if not (assigned & mine):  # admin alone is NOT enough (M4-D10)
        raise HTTPException(status.HTTP_403_FORBIDDEN,
                            detail="Not a member of any team assigned to this controller")

    if controller.last_sync_status == "running":  # best-effort fast pre-check; lock is the real guard
        raise HTTPException(status.HTTP_409_CONFLICT, detail="A sync is already running")

    await write_audit(db, action="awx_sync_manual", actor_id=user.id,
                      target_type="awx_controller", target_id=str(controller_id),
                      ip=client_ip(request))
    await db.commit()
    background.add_task(_run_manual_sync, str(controller_id))
    return SyncStartedOut(status="started")
