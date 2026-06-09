from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.collab_schemas import (
    AnnotationLink,
    AnnotationOut,
    CommentOut,
    NotificationOut,
    ShareOut,
    ShareTargetTeam,
    ShareTargetUser,
)
from app.models import Annotation, Comment, Notification, Run, RunShare, Team, User


def share_to_out(
    share: RunShare, user: User | None = None, team: Team | None = None
) -> ShareOut:
    return ShareOut(
        id=str(share.id),
        run_id=str(share.run_id),
        permission=share.permission,
        shared_by_user_id=str(share.shared_by_user_id),
        user=(
            ShareTargetUser(id=str(user.id), display_name=user.display_name, email=user.email)
            if user is not None else None
        ),
        team=(
            ShareTargetTeam(id=str(team.id), name=team.name, slug=team.slug)
            if team is not None else None
        ),
        created_at=share.created_at,
    )


def annotation_to_out(a: Annotation, *, author_name: str) -> AnnotationOut:
    return AnnotationOut(
        id=str(a.id),
        run_id=str(a.run_id),
        task_seq=a.task_seq,
        author_user_id=str(a.author_user_id),
        author_name=author_name,
        note=a.note,
        tags=list(a.tags or []),
        links=[AnnotationLink(**lk) for lk in (a.links or [])],
        resolved=a.resolved,
        created_at=a.created_at,
        updated_at=a.updated_at,
    )


def comment_to_out(c: Comment, *, author_name: str) -> CommentOut:
    deleted = c.deleted_at is not None
    return CommentOut(
        id=str(c.id),
        run_id=str(c.run_id),
        task_seq=c.task_seq,
        annotation_id=str(c.annotation_id) if c.annotation_id else None,
        parent_id=str(c.parent_id) if c.parent_id else None,
        author_user_id=str(c.author_user_id),  # author FK is CASCADE -> never null
        author_name=author_name,
        body=None if deleted else c.body,  # tombstone hides text
        mentions=[str(m) for m in (c.mentions or [])],
        created_at=c.created_at,
        edited_at=c.edited_at,
        deleted_at=c.deleted_at,
    )


async def resolve_visible_mentions(
    db: AsyncSession, run: Run, candidate_ids: list[str],
) -> list[tuple[uuid.UUID, str]]:
    """Keep each submitted mention id only if it is a real active user who can see `run`.

    Returns (id, display_name) for survivors, de-duped, preserving submission order.
    Drops invalid uuids / non-existent users / inactive users / non-visible users silently
    (no 403, no leak).
    """
    from app.services.visibility import is_run_visible  # avoid circular import at module level

    seen: set[uuid.UUID] = set()
    parsed: list[uuid.UUID] = []
    for raw in candidate_ids:
        try:
            uid = uuid.UUID(raw)
        except (ValueError, AttributeError, TypeError):
            continue
        if uid not in seen:
            seen.add(uid)
            parsed.append(uid)

    if not parsed:
        return []

    # Batch-load all candidate users in ONE query, then filter.
    rows = (await db.execute(
        select(User).where(User.id.in_(parsed))
    )).scalars().all()
    user_map: dict[uuid.UUID, User] = {u.id: u for u in rows}

    survivors: list[tuple[uuid.UUID, str]] = []
    for uid in parsed:
        u = user_map.get(uid)
        if u is None or not u.is_active:
            continue
        if await is_run_visible(db, run, u):
            survivors.append((u.id, u.display_name))
    return survivors


def notification_to_out(
    n: Notification,
    *,
    actor_names: dict,
    run_templates: dict,
    comment_info: dict,
    task_names: dict,
) -> NotificationOut:
    """Pure synchronous mapper — all data arrives pre-batched, zero DB calls.

    Parameters
    ----------
    n:
        The Notification row.
    actor_names:
        ``{actor_user_id: display_name}`` pre-fetched for the page.
    run_templates:
        ``{run_id: template_name}`` pre-fetched for the page.
    comment_info:
        ``{comment_id: (run_id, task_seq)}`` pre-fetched for the page.
    task_names:
        ``{(run_id, seq): task.name}`` pre-fetched for the page.

    A SET-NULL'd run_id/comment_id (deleted run) degrades gracefully to None
    fields so the inbox renders a "this run was deleted" state.
    """
    actor_name: str | None = None
    run_template: str | None = None
    task_seq: int | None = None
    task_name: str | None = None

    if n.actor_user_id is not None:
        actor_name = actor_names.get(n.actor_user_id)

    if n.run_id is not None:
        run_template = run_templates.get(n.run_id)

    if n.comment_id is not None:
        info = comment_info.get(n.comment_id)
        if info is not None:
            _cmt_run_id, task_seq = info
            if task_seq is not None and n.run_id is not None:
                task_name = task_names.get((n.run_id, task_seq))

    return NotificationOut(
        id=str(n.id),
        type=n.type,
        run_id=str(n.run_id) if n.run_id else None,
        run_template=run_template,
        task_seq=task_seq,
        task_name=task_name,
        actor_user_id=str(n.actor_user_id) if n.actor_user_id else None,
        actor_name=actor_name,
        read_at=n.read_at,
        created_at=n.created_at,
    )
