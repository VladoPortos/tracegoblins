from __future__ import annotations

import uuid

from sqlalchemy import or_, select
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


def links_out(raw) -> list[AnnotationLink]:
    """JSONB list-of-{label,url} → list[AnnotationLink], defensive against malformed stored rows
    (LINK1) — shared by the annotation and KB mappers so neither 500s on a bad link."""
    out: list[AnnotationLink] = []
    for lk in raw or []:
        if isinstance(lk, dict) and "url" in lk:
            out.append(AnnotationLink(label=lk.get("label", ""), url=lk["url"]))
    return out


def annotation_to_out(a: Annotation, *, author_name: str) -> AnnotationOut:
    return AnnotationOut(
        id=str(a.id),
        run_id=str(a.run_id),
        task_seq=a.task_seq,
        author_user_id=str(a.author_user_id),
        author_name=author_name,
        note=a.note,
        tags=list(a.tags or []),
        links=links_out(a.links),
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
    active = [uid for uid in parsed if (u := user_map.get(uid)) is not None and u.is_active]
    if not active:
        return []

    # Visibility batched at the RUN level (MENT1) — the same 5 branches as is_run_visible, but each
    # run-scoped fact is queried ONCE for all candidates instead of per user. KEEP IN SYNC WITH
    # app.services.visibility.is_run_visible.
    from collections import defaultdict

    from app.models import ControllerTeam, RunShare, TeamMember
    teams_by_user: dict[uuid.UUID, set[uuid.UUID]] = defaultdict(set)
    all_teams: set[uuid.UUID] = set()
    for uid, tid in (await db.execute(
        select(TeamMember.user_id, TeamMember.team_id).where(TeamMember.user_id.in_(active))
    )).all():
        teams_by_user[uid].add(tid)
        all_teams.add(tid)

    direct_uids = set((await db.execute(
        select(RunShare.shared_with_user_id).where(
            RunShare.run_id == run.id, RunShare.shared_with_user_id.in_(active))
    )).scalars().all())
    share_tids = set((await db.execute(
        select(RunShare.shared_with_team_id).where(
            RunShare.run_id == run.id, RunShare.shared_with_team_id.in_(all_teams))
    )).scalars().all()) if all_teams else set()
    awx_tids: set[uuid.UUID] = set()
    if run.source == "awx" and run.controller_id is not None and all_teams:
        awx_tids = set((await db.execute(
            select(ControllerTeam.team_id).where(
                ControllerTeam.controller_id == run.controller_id,
                ControllerTeam.team_id.in_(all_teams),
                or_(ControllerTeam.awx_organization_id.is_(None),
                    ControllerTeam.awx_organization_id == run.awx_organization_id),
            )
        )).scalars().all())

    survivors: list[tuple[uuid.UUID, str]] = []
    for uid in active:
        my_teams = teams_by_user[uid]
        visible = (
            run.owner_user_id == uid
            or (run.team_id is not None and run.team_id in my_teams)
            or uid in direct_uids
            or bool(my_teams & share_tids)
            or bool(my_teams & awx_tids)
        )
        if visible:
            survivors.append((uid, user_map[uid].display_name))
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
