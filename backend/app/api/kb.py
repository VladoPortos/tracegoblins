from __future__ import annotations

import uuid

import sqlalchemy as sa
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.collab_schemas import AnnotationLink
from app.api.deps import AdminUser, CurrentUser, DbSession, GatedUser, require_password_current
from app.api.http_utils import client_ip
from app.api.validation import resolve_team_or_422
from app.api.kb_schemas import (
    KB_STATUS_VALUES,
    PromoteIn,
    SignatureCreate,
    SignatureOut,
    SignatureUpdate,
    SuggestOut,
)
from app.kb.service import backfill_signature, visible_occurrence_count, visible_occurrence_counts
from app.kb.signature import extract_signature
from app.models import KbSignature, Run, Task, TeamMember, User
from app.services.audit import write_audit
from app.services.collab_validate import validate_links
from app.services.visibility import is_run_visible, kb_visibility_cond, my_team_ids

router = APIRouter(prefix="/api/kb", tags=["kb"])


def _links_out(raw) -> list[AnnotationLink]:
    """JSONB list-of-{label,url} -> list[AnnotationLink] (defensive against bad rows)."""
    out: list[AnnotationLink] = []
    for lk in raw or []:
        if isinstance(lk, dict) and "url" in lk:
            out.append(AnnotationLink(label=lk.get("label", ""), url=lk["url"]))
    return out


def signature_to_out(sig: KbSignature, *, occurrence_count: int) -> SignatureOut:
    return SignatureOut(
        id=str(sig.id),
        team_id=str(sig.team_id) if sig.team_id is not None else None,
        signature_key=sig.signature_key,
        title=sig.title,
        status=sig.status,
        category=sig.category,
        description=sig.description,
        is_problem=sig.is_problem,
        where_it_lives=sig.where_it_lives,
        representative_text=sig.representative_text,
        links=_links_out(sig.links),
        occurrence_count=occurrence_count,
        created_at=sig.created_at,
        updated_at=sig.updated_at,
    )


async def _signature_visible(db: AsyncSession, sig: KbSignature, user: User) -> bool:
    """Visible iff global (team_id NULL) OR U is a member of the signature's team.

    A1: an admin role grants NO read path here — visibility is relationship-based.
    """
    if sig.team_id is None:
        return True
    return sig.team_id in await my_team_ids(db, user)


async def _get_visible_signature(db: AsyncSession, sig_id: uuid.UUID, user: User) -> KbSignature:
    """Load + visibility-gate a signature. Not visible / missing -> 404 (never 403)."""
    sig = await db.get(KbSignature, sig_id)
    if sig is None or not await _signature_visible(db, sig, user):
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Signature not found")
    return sig


@router.get("/signatures", response_model=list[SignatureOut])
async def list_signatures(
    user: CurrentUser, db: DbSession,
    scope: str = Query("all", pattern="^(team|global|all)$"),
    status_: str | None = Query(None, alias="status"),
    q: str | None = Query(None),
):
    team_ids = await my_team_ids(db, user)
    if scope == "global":
        scope_cond = KbSignature.team_id.is_(None)
    elif scope == "team":
        # sa.false() (a SQL FALSE), NOT a Python `False`, so an empty-team caller yields an
        # empty result set cleanly inside .where(...) — matching run_visible_cond
        # (app/services/visibility.py).
        scope_cond = (
            KbSignature.team_id.in_(team_ids) if team_ids else sa.false()
        )
    else:  # all
        scope_cond = kb_visibility_cond(team_ids)

    stmt = select(KbSignature).where(scope_cond)
    if status_ is not None:
        stmt = stmt.where(KbSignature.status == status_)
    if q:
        like = f"%{q}%"
        stmt = stmt.where(
            or_(KbSignature.title.ilike(like), KbSignature.representative_text.ilike(like))
        )
    stmt = stmt.order_by(KbSignature.updated_at.desc()).limit(200)

    rows = (await db.execute(stmt)).scalars().all()
    # Batched: ONE grouped count query for all listed signatures (avoids an N+1 over the list).
    counts = await visible_occurrence_counts(db, [s.id for s in rows], user)
    return [signature_to_out(sig, occurrence_count=counts.get(sig.id, 0)) for sig in rows]


@router.get("/signatures/{sig_id}", response_model=SignatureOut)
async def get_signature(sig_id: uuid.UUID, user: CurrentUser, db: DbSession):
    sig = await _get_visible_signature(db, sig_id, user)
    n = await visible_occurrence_count(db, sig.id, user)
    return signature_to_out(sig, occurrence_count=n)


def _validate_status(value: str) -> str:
    if value not in KB_STATUS_VALUES:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"Unknown status '{value}'",
        )
    return value


async def _authorize_target_team(
    db: AsyncSession, user: User, team_id_raw: str | None
) -> uuid.UUID | None:
    """Resolve + authorize the target scope. None => global (admin only). Else U must be a member."""
    if team_id_raw is None:
        if user.role != "admin":
            raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Global KB requires admin")
        return None
    team = await resolve_team_or_422(db, team_id_raw)
    if await db.get(TeamMember, (team.id, user.id)) is None:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Not a member of that team")
    return team.id


@router.post("/signatures", status_code=201, response_model=SignatureOut)
async def create_signature(
    payload: SignatureCreate, request: Request, db: DbSession, user: GatedUser,
):
    _validate_status(payload.status)
    links = validate_links(payload.links)
    team_id = await _authorize_target_team(db, user, payload.team_id)

    sig = KbSignature(
        team_id=team_id,
        signature_key=payload.signature_key,
        title=payload.title,
        status=payload.status,
        category=payload.category,
        description=payload.description,
        is_problem=payload.is_problem,
        where_it_lives=payload.where_it_lives,
        representative_text=payload.representative_text,
        match_patterns=payload.match_patterns or {},
        links=links,
        created_by_user_id=user.id,
    )
    db.add(sig)
    try:
        await db.flush()  # surfaces the NULL-distinct partial-unique violation on a dup key
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, detail="Signature already exists for this key")

    # commit=False: the backfilled occurrences + the signature insert + the audit row all
    # land in this route's single final db.commit() below (atomic — a failure before that
    # commit leaves NEITHER the signature NOR an audit row).
    await backfill_signature(db, sig, commit=False)
    await write_audit(
        db, action="kb_create", actor_id=user.id, target_type="kb_signature",
        target_id=str(sig.id), ip=client_ip(request),
        metadata={"signature_key": sig.signature_key,
                  "team_id": str(team_id) if team_id else None},
    )
    await db.commit()
    await db.refresh(sig)
    n = await visible_occurrence_count(db, sig.id, user)
    return signature_to_out(sig, occurrence_count=n)


async def _authorize_edit(db: AsyncSession, sig: KbSignature, user: User) -> None:
    """Edit/delete gate (caller has ALREADY passed the visibility gate).

    Global sig -> admin only. Team sig -> any member of that team.
    """
    if sig.team_id is None:
        if user.role != "admin":
            raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Global KB requires admin")
        return
    if await db.get(TeamMember, (sig.team_id, user.id)) is None:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Not a member of that team")


@router.patch("/signatures/{sig_id}", response_model=SignatureOut)
async def update_signature(
    sig_id: uuid.UUID, payload: SignatureUpdate, request: Request, db: DbSession, user: GatedUser,
):
    sig = await _get_visible_signature(db, sig_id, user)
    await _authorize_edit(db, sig, user)

    fields = payload.model_dump(exclude_unset=True)
    _NOT_NULL_FIELDS = {"title", "status", "representative_text"}
    for _f in _NOT_NULL_FIELDS:
        if _f in fields and fields[_f] is None:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=f"'{_f}' may not be set to null",
            )
    if "status" in fields and fields["status"] is not None:
        _validate_status(fields["status"])
    if "links" in fields and fields["links"] is not None:
        sig.links = validate_links(payload.links)
        fields.pop("links")
    if "match_patterns" in fields:
        sig.match_patterns = fields.pop("match_patterns") or {}
    for attr in ("title", "status", "representative_text", "category",
                 "description", "is_problem", "where_it_lives"):
        if attr in fields:
            setattr(sig, attr, fields[attr])

    await db.flush()
    # commit=False: occurrences + edits + audit row commit together in the final db.commit().
    await backfill_signature(db, sig, commit=False)
    await write_audit(
        db, action="kb_edit", actor_id=user.id, target_type="kb_signature",
        target_id=str(sig.id), ip=client_ip(request),
        metadata={"signature_key": sig.signature_key},
    )
    await db.commit()
    await db.refresh(sig)
    n = await visible_occurrence_count(db, sig.id, user)
    return signature_to_out(sig, occurrence_count=n)


async def _visible_run(db: AsyncSession, run_id_raw: str, user: User) -> Run:
    """Load + visibility-gate a run by its raw string id (404 on bad id / missing / invisible)."""
    try:
        rid = uuid.UUID(run_id_raw)
    except (ValueError, AttributeError):
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Run not found")
    run = await db.get(Run, rid)
    if run is None or not await is_run_visible(db, run, user):
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Run not found")
    return run


async def _load_task(db: AsyncSession, run: Run, task_seq: int) -> Task:
    t = await db.scalar(select(Task).where(Task.run_id == run.id, Task.seq == task_seq))
    if t is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Task not found")
    return t


@router.get("/suggest", response_model=SuggestOut)
async def suggest_signature(
    user: CurrentUser, db: DbSession,
    run_id: str = Query(...), task_seq: int = Query(...),
):
    run = await _visible_run(db, run_id, user)
    task = await _load_task(db, run, task_seq)
    sig = extract_signature(task.error)
    if sig is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT,
                            detail="Task has no extractable error")
    return SuggestOut(
        signature_key=sig.signature_key,
        representative_text=sig.representative_text,
        category=sig.category,
    )


@router.delete("/signatures/{sig_id}", status_code=204)
async def delete_signature(
    sig_id: uuid.UUID, request: Request, db: DbSession, user: GatedUser,
):
    sig = await _get_visible_signature(db, sig_id, user)
    await _authorize_edit(db, sig, user)
    await db.delete(sig)  # cascades kb_occurrences via ondelete=CASCADE
    await write_audit(
        db, action="kb_delete", actor_id=user.id, target_type="kb_signature",
        target_id=str(sig_id), ip=client_ip(request),
        metadata={"signature_key": sig.signature_key},
    )
    await db.commit()
    return None


@router.post("/promote", status_code=201, response_model=SignatureOut)
async def promote_signature(
    payload: PromoteIn, request: Request, db: DbSession, user: GatedUser,
):
    run = await _visible_run(db, payload.run_id, user)
    task = await _load_task(db, run, payload.task_seq)
    extracted = extract_signature(task.error)
    if extracted is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT,
                            detail="Task has no extractable error")
    _validate_status(payload.status)
    links = validate_links(payload.links)
    team_id = await _authorize_target_team(db, user, payload.team_id)

    sig = KbSignature(
        team_id=team_id,
        signature_key=extracted.signature_key,       # server-extracted, authoritative
        title=payload.title,
        status=payload.status,
        category=extracted.category,
        description=payload.description,
        is_problem=payload.is_problem,
        where_it_lives=payload.where_it_lives,
        representative_text=extracted.representative_text,
        match_patterns={},
        links=links,
        created_by_user_id=user.id,
    )
    db.add(sig)
    try:
        await db.flush()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, detail="Signature already exists for this key")

    # commit=False: the originating run's occurrence + the signature + the audit row all
    # commit together in the final db.commit() (atomic).
    await backfill_signature(db, sig, commit=False)
    await write_audit(db, action="kb_promote", actor_id=user.id, target_type="kb_signature",
                      target_id=str(sig.id), ip=client_ip(request),
                      metadata={"signature_key": sig.signature_key, "run_id": str(run.id),
                                "task_seq": payload.task_seq})
    await db.commit()
    await db.refresh(sig)
    n = await visible_occurrence_count(db, sig.id, user)
    return signature_to_out(sig, occurrence_count=n)


@router.post(
    "/signatures/{sig_id}/promote-global",
    response_model=SignatureOut,
    dependencies=[Depends(require_password_current)],  # same forced-change gate as sibling mutations
)
async def promote_signature_global(
    sig_id: uuid.UUID, request: Request, db: DbSession, user: AdminUser,
):
    # A1: admin role grants NO read path — go through the same visibility gate every other KB
    # mutation uses (raw db.get() would let a non-member admin act on, and leak, a team's
    # private KB entry). For a team signature this requires the admin to be a member of that
    # team; missing/invisible -> 404 (never 403).
    sig = await _get_visible_signature(db, sig_id, user)
    if sig.team_id is None:
        # Already global: idempotent no-op (count + return). No second global row created.
        n = await visible_occurrence_count(db, sig.id, user)
        return signature_to_out(sig, occurrence_count=n)

    sig.team_id = None
    try:
        await db.flush()  # global partial-unique: another global for this key -> conflict
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT,
                            detail="A global signature already exists for this key")

    # commit=False: the now-global re-scan's occurrences + the team_id->NULL change + the
    # audit row all commit together in the final db.commit() (atomic).
    await backfill_signature(db, sig, commit=False)  # now global => scans all runs in scope
    await write_audit(db, action="kb_promote_global", actor_id=user.id, target_type="kb_signature",
                      target_id=str(sig.id), ip=client_ip(request),
                      metadata={"signature_key": sig.signature_key})
    await db.commit()
    await db.refresh(sig)
    n = await visible_occurrence_count(db, sig.id, user)
    return signature_to_out(sig, occurrence_count=n)
