from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException, Request, Response, status

from app.api.collab_schemas import AnnotationOut, AnnotationUpdate
from app.api.deps import DbSession, GatedUser
from app.api.http_utils import client_ip
from app.models import Annotation, Run, User
from app.services.audit import write_audit
from app.services.collab_query import annotation_to_out
from app.services.collab_validate import validate_links, validate_tags
from app.services.visibility import is_run_visible

router = APIRouter(prefix="/api/annotations", tags=["annotations"])


async def _load_visible_annotation(
    aid: uuid.UUID, user: User, db
) -> tuple[Annotation, Run]:
    """Load the annotation and its run, gate on visibility (404 if not visible).

    Uses the single is_run_visible predicate (A3) — no second copy of the 4-way logic.
    """
    a = await db.get(Annotation, aid)
    if a is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Annotation not found")
    run = await db.get(Run, a.run_id)
    if run is None or not await is_run_visible(db, run, user):
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Annotation not found")  # 404, no leak
    return a, run


@router.patch("/{aid}", response_model=AnnotationOut)
async def update_annotation(
    aid: uuid.UUID, payload: AnnotationUpdate, request: Request, db: DbSession, user: GatedUser,
):
    a, run = await _load_visible_annotation(aid, user, db)
    if a.author_user_id != user.id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Author only")
    if payload.note is not None:
        a.note = payload.note
    if payload.tags is not None:
        a.tags = validate_tags(payload.tags)
    if payload.links is not None:
        a.links = validate_links(payload.links)
    if payload.resolved is not None:
        a.resolved = payload.resolved
    await write_audit(db, action="annotation_update", actor_id=user.id,
                      target_type="run", target_id=str(run.id), ip=client_ip(request))
    await db.commit()
    await db.refresh(a)
    # Re-load author display_name for denormalized response
    author = await db.get(User, a.author_user_id)
    author_name = author.display_name if author is not None else user.display_name
    return annotation_to_out(a, author_name=author_name)


@router.delete("/{aid}", status_code=204)
async def delete_annotation(
    aid: uuid.UUID, request: Request, db: DbSession, user: GatedUser,
):
    a, run = await _load_visible_annotation(aid, user, db)
    if a.author_user_id != user.id and run.owner_user_id != user.id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Author or run owner only")
    await db.delete(a)
    await write_audit(db, action="annotation_delete", actor_id=user.id,
                      target_type="run", target_id=str(run.id), ip=client_ip(request))
    await db.commit()
    return Response(status_code=204)
