from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import func, select, tuple_, update

from app.api.collab_schemas import MarkReadIn, NotificationListOut, UnreadCountOut
from app.api.deps import CurrentUser, DbSession, GatedUser
from app.models import Comment, Notification, Run, Task, User
from app.services.collab_query import notification_to_out

router = APIRouter(prefix="/api/notifications", tags=["notifications"])


@router.get("", response_model=NotificationListOut)
async def list_notifications(
    user: CurrentUser,
    db: DbSession,
    unread_only: bool = Query(False),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
) -> NotificationListOut:
    base = select(Notification).where(Notification.user_id == user.id)
    if unread_only:
        base = base.where(Notification.read_at.is_(None))

    total = await db.scalar(
        select(func.count()).select_from(base.subquery())
    )
    unread = await db.scalar(
        select(func.count()).select_from(Notification).where(
            Notification.user_id == user.id, Notification.read_at.is_(None)
        )
    )
    rows = (await db.execute(
        base.order_by(Notification.created_at.desc()).limit(limit).offset(offset)
    )).scalars().all()

    # ------------------------------------------------------------------ #
    # Batch all denormalization lookups across the page — zero per-row N+1.
    # ------------------------------------------------------------------ #

    # 1. Actor display names.
    actor_ids = {n.actor_user_id for n in rows if n.actor_user_id is not None}
    actor_names: dict = {}
    if actor_ids:
        actor_names = {
            uid: name for uid, name in (await db.execute(
                select(User.id, User.display_name).where(User.id.in_(actor_ids))
            )).all()
        }

    # 2. Run template names.
    run_ids = {n.run_id for n in rows if n.run_id is not None}
    run_templates: dict = {}
    if run_ids:
        run_templates = {
            rid: tname for rid, tname in (await db.execute(
                select(Run.id, Run.template_name).where(Run.id.in_(run_ids))
            )).all()
        }

    # 3. Comment → (run_id, task_seq) mapping.
    comment_ids = {n.comment_id for n in rows if n.comment_id is not None}
    comment_info: dict = {}
    if comment_ids:
        comment_info = {
            cid: (crun_id, tseq) for cid, crun_id, tseq in (await db.execute(
                select(Comment.id, Comment.run_id, Comment.task_seq)
                .where(Comment.id.in_(comment_ids))
            )).all()
        }

    # 4. Task names keyed by (run_id, seq).
    task_names: dict = {}
    pairs = [
        (crun_id, tseq)
        for crun_id, tseq in comment_info.values()
        if crun_id is not None and tseq is not None
    ]
    if pairs:
        task_names = {
            (trun_id, tseq): tname
            for trun_id, tseq, tname in (await db.execute(
                select(Task.run_id, Task.seq, Task.name)
                .where(tuple_(Task.run_id, Task.seq).in_(pairs))
            )).all()
        }

    items = [
        notification_to_out(
            n,
            actor_names=actor_names,
            run_templates=run_templates,
            comment_info=comment_info,
            task_names=task_names,
        )
        for n in rows
    ]
    return NotificationListOut(items=items, total=total or 0, unread=unread or 0)


@router.get("/unread_count", response_model=UnreadCountOut)
async def unread_count(user: CurrentUser, db: DbSession) -> UnreadCountOut:
    count = await db.scalar(
        select(func.count()).select_from(Notification).where(
            Notification.user_id == user.id, Notification.read_at.is_(None)
        )
    )
    return UnreadCountOut(count=count or 0)


@router.post("/read", response_model=UnreadCountOut)
async def mark_read(payload: MarkReadIn, user: GatedUser, db: DbSession) -> UnreadCountOut:
    if not payload.all and not payload.ids:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Provide ids[] or all=true",
        )

    stmt = (
        update(Notification)
        .where(Notification.user_id == user.id, Notification.read_at.is_(None))
        .values(read_at=func.now())
    )
    if not payload.all:
        try:
            ids = [uuid.UUID(i) for i in payload.ids or []]
        except ValueError:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT, detail="Invalid id"
            )
        stmt = stmt.where(Notification.id.in_(ids))

    await db.execute(stmt)
    count = await db.scalar(
        select(func.count()).select_from(Notification).where(
            Notification.user_id == user.id, Notification.read_at.is_(None)
        )
    )
    await db.commit()
    return UnreadCountOut(count=count or 0)
