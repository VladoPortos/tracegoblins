from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException, Request, status
from sqlalchemy import func

from app.api.collab_schemas import CommentOut, CommentUpdate
from app.api.deps import DbSession, GatedUser
from app.api.http_utils import client_ip
from app.api.runs import _comment_out_with_names
from app.models import Comment, Run, User
from app.services.audit import write_audit
from app.services.collab_query import resolve_visible_mentions
from app.services.notifications import create_mention_notifications
from app.services.visibility import is_run_visible

router = APIRouter(prefix="/api/comments", tags=["comments"])


async def _load_visible_comment(cid: uuid.UUID, user: User, db) -> tuple[Comment, Run]:
    """Load comment + its run, gate on run visibility (404 if not visible — no leak)."""
    c = await db.get(Comment, cid)
    if c is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Comment not found")
    run = await db.get(Run, c.run_id)
    if run is None or not await is_run_visible(db, run, user):
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Comment not found")
    return c, run


@router.patch("/{cid}", response_model=CommentOut)
async def update_comment(
    cid: uuid.UUID, payload: CommentUpdate, db: DbSession, user: GatedUser,
):
    c, run = await _load_visible_comment(cid, user, db)
    if c.author_user_id != user.id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Author only")

    # Re-validate submitted mentions[] against run-visible users; drop the rest silently.
    # Capture previous set before reassignment so C5 can notify only newly-added ids.
    previous = set(c.mentions or [])
    survivors = [uid for uid, _name in await resolve_visible_mentions(db, run, payload.mentions)]

    c.body = payload.body
    c.mentions = survivors
    c.edited_at = func.now()
    await db.flush()
    newly_added = [uid for uid in survivors if uid not in previous]
    await create_mention_notifications(
        db, comment=c, mention_ids=newly_added, actor_id=user.id
    )
    await db.commit()
    await db.refresh(c)
    return await _comment_out_with_names(c, db)


@router.delete("/{cid}", response_model=CommentOut)
async def delete_comment(
    cid: uuid.UUID, request: Request, db: DbSession, user: GatedUser,
):
    c, run = await _load_visible_comment(cid, user, db)
    if c.author_user_id != user.id and run.owner_user_id != user.id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Author or run owner only")

    # Soft-delete: set deleted_at; body is hidden in the tombstone response.
    c.deleted_at = func.now()
    await write_audit(
        db, action="comment_delete", actor_id=user.id,
        target_type="run", target_id=str(run.id), ip=client_ip(request),
    )
    await db.commit()
    await db.refresh(c)
    return await _comment_out_with_names(c, db)  # 200 + tombstone (body=None)
