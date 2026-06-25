from __future__ import annotations

import json
import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile, status
from fastapi.responses import PlainTextResponse
from sqlalchemy import BigInteger, and_, case, cast, func, nulls_last, or_, select, text
from sqlalchemy.exc import IntegrityError

from app.api.collab_schemas import AnnotationCreate, AnnotationOut, CommentCreate, CommentOut, MentionableUser, ShareCreate, ShareOut
from app.api.deps import CurrentUser, DbSession, GatedUser
from app.api.path_schemas import (
    EnterToOut, NodeResultOut, NodeResultsPageOut, PathEdgeOut, PathNodeOut,
    PathTreeOut, PathViewOut, RunInputsOut,
)
from app.api.http_utils import client_ip
from app.api.kb_schemas import KbSuggestionOut
from app.api.validation import parse_uuid_or_422, resolve_team_or_422
from app.api.runs_schemas import FacetController, FacetOrg, FacetsOut, RunCreated, RunDetail, RunDiffOut, RunList, TaskFull, TaskLean
from app.models import Annotation, AwxController, Comment, ControllerTeam, KbOccurrence, KbSignature, Run, RunNode, RunNodeResult, RunRaw, RunShare, Task, Team, TeamMember, User
from app.services.audit import write_audit
from app.services.notifications import create_mention_notifications, create_share_notifications
from app.services.collab_query import annotation_to_out, comment_to_out, resolve_visible_mentions, share_to_out
from app.services.collab_validate import validate_links, validate_tags
from app.services.visibility import is_run_visible, kb_visibility_cond, my_team_ids
from app.services.ingestion import MAX_UPLOAD_BYTES, ingest_upload
from app.services.run_diff import diff_tasks, find_baseline, recap_newly_unreachable
from app.services.run_time import run_when_expr
from app.services.runs_query import run_to_card, run_to_detail, task_to_full, task_to_lean
from app.kb.signature import extract_signature
from app.kb.service import visible_occurrence_count

import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/runs", tags=["runs"])


async def _read_body_capped(request: Request, cap: int) -> bytes:
    """Stream the raw request body with a HARD byte cap, independent of Content-Length.

    request.json() buffers the whole body before any size check, so a chunked / missing-
    Content-Length body could OOM the worker before the 8 MB guard runs. Accumulating from
    the raw stream and aborting the moment the cap is exceeded bounds memory regardless of
    how the client frames the request."""
    chunks: list[bytes] = []
    total = 0
    async for chunk in request.stream():
        total += len(chunk)
        if total > cap:
            raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, detail="Upload too large.")
        chunks.append(chunk)
    return b"".join(chunks)


async def get_visible_run(run_id: uuid.UUID, user: CurrentUser, db: DbSession) -> Run:
    """Return the run iff U can see it (owner ∪ team-owned ∪ direct-share ∪ team-share); else 404.

    A1: admin role grants NO path here.
    """
    run = await db.get(Run, run_id)
    if run is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Run not found")
    if not await is_run_visible(db, run, user):
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Run not found")  # 404, never 403
    return run


VisibleRun = Annotated[Run, Depends(get_visible_run)]


async def get_owned_run(run: VisibleRun, user: CurrentUser) -> Run:
    """Layer an owner gate on top of visibility: not-visible -> 404, visible-non-owner -> 403."""
    if run.owner_user_id != user.id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Owner only")
    return run


OwnedRun = Annotated[Run, Depends(get_owned_run)]


async def _require_task(db: DbSession, run_id: uuid.UUID, seq: int) -> None:
    """404 unless a Task (run_id, seq) actually exists — annotations/comments carry a bare
    task_seq with no FK to tasks, so without this an arbitrary seq would create an orphan."""
    exists = await db.scalar(
        select(Task.seq).where(Task.run_id == run_id, Task.seq == seq).limit(1)
    )
    if exists is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Task not found")


@router.post("", status_code=201, response_model=RunCreated)
async def create_run(
    request: Request,
    db: DbSession,
    user: GatedUser,
    file: Annotated[UploadFile | None, File()] = None,
    template: Annotated[str | None, Form()] = None,
    team_id: Annotated[str | None, Form()] = None,
):
    ctype = request.headers.get("content-type", "")
    if ctype.startswith("multipart/form-data"):
        # Multipart parts spool to disk; cheaply reject an oversized body via Content-Length
        # before reading the file (the precise file.size check below stays authoritative).
        cl = request.headers.get("content-length")
        if cl and cl.isdigit() and int(cl) > MAX_UPLOAD_BYTES + 1_048_576:  # +1MB slack for multipart boundary overhead
            raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, "Upload too large.")
        if file is None:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail="file is required")
        if file.size is not None and file.size > MAX_UPLOAD_BYTES:
            raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, detail="Log exceeds 8 MB")
        # Bounded read: read(n) never pulls more than cap+1 into memory even if file.size was
        # unavailable (a chunked multipart part can leave it unset). _guard_and_decode stays
        # authoritative on the exact 8 MB limit for the decoded text.
        raw_bytes = await file.read(MAX_UPLOAD_BYTES + 1)
        if len(raw_bytes) > MAX_UPLOAD_BYTES:
            raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, detail="Log exceeds 8 MB")
        tmpl = template
        team_raw = team_id
    else:
        # Reject an oversized JSON body via Content-Length BEFORE buffering it into memory
        # (mirrors the multipart pre-check above). _guard_and_decode stays authoritative for
        # bodies that slip past this (e.g. chunked without Content-Length).
        cl = request.headers.get("content-length")
        if cl and cl.isdigit() and int(cl) > MAX_UPLOAD_BYTES + 1_048_576:  # +1MB JSON envelope slack
            raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, detail="Upload too large.")
        # Authoritative cap for bodies that slip past the Content-Length check (chunked / no CL):
        # stream with a hard byte ceiling so request.json() can't buffer an unbounded body.
        raw = await _read_body_capped(request, MAX_UPLOAD_BYTES + 1_048_576)
        try:
            body = json.loads(raw)
        except Exception:
            raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                                detail="Expected multipart file or JSON {text}")
        text = body.get("text") if isinstance(body, dict) else None
        if not isinstance(text, str) or not text.strip():
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail="text is required")
        raw_bytes = text.encode("utf-8")
        tmpl = body.get("template") if isinstance(body, dict) else None
        team_raw = body.get("team_id") if isinstance(body, dict) else None

    target_team_id: uuid.UUID | None = None
    if team_raw:
        target_team_id = parse_uuid_or_422(team_raw, detail="Invalid team_id")
        # Membership-checked: non-member (or unknown team) -> 403, never silently personal.
        if await db.get(TeamMember, (target_team_id, user.id)) is None:
            raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Not a member of that team")

    run = await ingest_upload(db, owner=user, raw_bytes=raw_bytes, template_override=tmpl,
                              team_id=target_team_id, ip=client_ip(request))
    await db.commit()

    # Best-effort KB matching, post-commit. Local import keeps app.kb off the hot import
    # path; a matcher/extraction error must never fail an already-persisted upload.
    from app.kb.service import match_run
    try:
        await match_run(db, run)
    except Exception:
        logger.exception("kb match_run failed for run %s", run.id)

    return RunCreated(id=str(run.id))


def _when_expr():
    """The run's effective timestamp: prefer AWX launch, then finish/log, then import.

    Thin alias over app.services.run_time.run_when_expr so the coalesce ordering rule
    is defined in exactly one place; kept as a local name for the existing call sites.
    """
    return run_when_expr()


def _job_id_num():
    """awx_job_id as a sortable bigint; non-numeric / empty / NULL / >18 digits -> NULL (sorts last).

    awx_job_id can come from uploaded log content (the 'Job Id:' line), so a pathologically
    long digit string would overflow the bigint cast and 500 the sort query. Guard the length
    first; bigint comfortably holds 18 digits.
    """
    digits = func.nullif(func.regexp_replace(Run.awx_job_id, r"\D", "", "g"), "")
    return case((func.length(digits) <= 18, digits), else_=None)


def _runs_order_by(sort: str, direction: str):
    """ORDER BY expressions for the run list. Nulls always last; stable id tiebreaker."""
    if sort == "job_id":
        col = cast(_job_id_num(), BigInteger)
    elif sort == "hosts":
        col = Run.host_count
    elif sort == "duration":
        col = Run.elapsed
    elif sort == "status":
        col = case(
            (Run.status == "unreachable", 0),
            (Run.status == "failed", 1),
            (Run.status == "changed", 2),
            (Run.status == "ok", 3),
            else_=4,
        )
    else:  # "when"
        col = _when_expr()
    ordered = col.asc() if direction == "asc" else col.desc()
    return [nulls_last(ordered), Run.id.asc()]


def _runs_extra_conditions(
    *, controller, organization, template, awx_user, status_csv,
    launch_type, launched_after, launched_before, search, source=None,
):
    """Build the AND-combined list of filter conditions applied AFTER the visibility scope."""
    extra = []
    if source is not None:
        extra.append(Run.source == source)
    if controller is not None:
        extra.append(Run.controller_id == parse_uuid_or_422(controller, detail="Invalid controller"))
    if organization is not None:
        extra.append(Run.awx_organization_id == organization)
    if template:
        extra.append(Run.template_name.ilike(f"%{template}%"))
    if awx_user:
        extra.append(Run.awx_user.ilike(f"%{awx_user}%"))
    if status_csv:
        wanted = [s.strip() for s in status_csv.split(",") if s.strip()]
        if wanted:
            extra.append(Run.status.in_(wanted))
    if launch_type:
        extra.append(Run.awx_launch_type == launch_type)
    when = _when_expr()
    if launched_after is not None:
        extra.append(when >= launched_after)
    if launched_before is not None:
        extra.append(when <= launched_before)
    if search:
        like = f"%{search}%"
        # Search is SERVER-side so every page is filtered before pagination — a client-only filter
        # over already-loaded pages reports false "no matches" for older runs. Cover the fields the
        # dashboard search box advertises: template, user, job id, org, workflow, team, recap host.
        recap_array = case(
            (func.jsonb_typeof(Run.recap) == "array", Run.recap),
            else_=text("'[]'::jsonb"),
        )
        host_match = (
            select(1)
            .select_from(func.jsonb_array_elements(recap_array).table_valued("value"))
            .where(text("value ->> 'host' ILIKE :host_like").bindparams(host_like=like))
            .correlate(Run)
            .exists()
        )
        extra.append(or_(
            Run.template_name.ilike(like),
            Run.awx_user.ilike(like),
            Run.awx_job_id.ilike(like),
            Run.awx_organization_name.ilike(like),
            Run.awx_workflow_name.ilike(like),
            Run.team_id.in_(select(Team.id).where(Team.name.ilike(like))),
            host_match,
        ))
    return extra


@router.get("", response_model=RunList)
async def list_runs(
    user: CurrentUser, db: DbSession,
    scope: str = Query("mine", pattern="^(mine|shared|team)$"),
    controller: str | None = Query(None),
    organization: int | None = Query(None),
    template: str | None = Query(None),
    awx_user: str | None = Query(None),
    status: str | None = Query(None),
    launch_type: str | None = Query(None),
    source: str | None = Query(None, pattern="^(upload|awx)$"),  # source chips: server-side scoping
    launched_after: datetime | None = Query(None),
    launched_before: datetime | None = Query(None),
    search: str | None = Query(None),
    sort: str = Query("when", pattern="^(when|job_id|hosts|duration|status)$"),
    dir: str = Query("desc", pattern="^(asc|desc)$"),
    limit: int = Query(20, ge=1, le=100), offset: int = Query(0, ge=0),
):
    extra = _runs_extra_conditions(
        controller=controller, organization=organization, template=template,
        awx_user=awx_user, status_csv=status, launch_type=launch_type, source=source,
        launched_after=launched_after, launched_before=launched_before, search=search,
    )

    if scope in ("mine", "shared"):
        # Non-team scopes share the same base predicate as run_filters (ONE source of truth).
        base = _scope_base_cond(scope, user)
        cond = and_(base, *extra)
        total = await db.scalar(select(func.count()).select_from(Run).where(cond))
        rows = (await db.execute(
            select(Run).where(cond).order_by(*_runs_order_by(sort, dir)).limit(limit).offset(offset)
        )).scalars().all()
        return RunList(items=[run_to_card(r) for r in rows], total=total or 0)

    # scope == "team": delegate to the shared _team_scope_base helper (ONE source of truth).
    team_ids = await my_team_ids(db, user)
    base = await _team_scope_base(db, user)
    if base is None:
        return RunList(items=[], total=0)
    cond = and_(base, *extra)
    total = await db.scalar(select(func.count()).select_from(Run).where(cond))
    rows = (await db.execute(
        select(Run).where(cond).order_by(*_runs_order_by(sort, dir)).limit(limit).offset(offset)
    )).scalars().all()

    # Batch-resolve controller names (avoid N+1 across AWX rows).
    controller_ids = {r.controller_id for r in rows if r.controller_id is not None}
    ctrl_name_map: dict[uuid.UUID, str] = {}
    if controller_ids:
        ctrls = (await db.scalars(
            select(AwxController).where(AwxController.id.in_(controller_ids))
        )).all()
        ctrl_name_map = {c.id: c.name for c in ctrls}

    # Resolve team names for grouping cards. Cache lookups to avoid N+1 on repeated teams.
    name_cache: dict[uuid.UUID, str | None] = {}

    async def _team_name(tid: uuid.UUID | None) -> str | None:
        if tid is None:
            return None
        if tid not in name_cache:
            t = await db.get(Team, tid)
            name_cache[tid] = t.name if t is not None else None
        return name_cache[tid]

    items: list = []
    for r in rows:
        ctrl_name = ctrl_name_map.get(r.controller_id) if r.controller_id else None
        if r.team_id is not None and r.team_id in team_ids:
            items.append(run_to_card(r, team_name=await _team_name(r.team_id), controller_name=ctrl_name))
        elif r.source == "awx":
            # AWX run: not team-owned; surfaced via controller_teams. No team attribution.
            items.append(run_to_card(r, controller_name=ctrl_name))
        else:
            shared_tid = await db.scalar(
                select(RunShare.shared_with_team_id).where(
                    RunShare.run_id == r.id,
                    RunShare.shared_with_team_id.in_(team_ids),
                ).limit(1)
            )
            card = run_to_card(r, team_name=await _team_name(shared_tid), controller_name=ctrl_name)
            card.team_id = str(shared_tid) if shared_tid else None
            items.append(card)
    return RunList(items=items, total=total or 0)


async def _team_scope_base(db, user):
    """The team-scope visibility condition (team-owned ∪ team-shared ∪ AWX-via-controller_teams,
    minus U's personal non-AWX uploads), or None when U is in no teams.
    Shared by list_runs + run_filters."""
    team_ids = await my_team_ids(db, user)
    if not team_ids:
        return None
    team_owned = Run.team_id.in_(team_ids)
    team_shared = Run.id.in_(
        select(RunShare.run_id).where(RunShare.shared_with_team_id.in_(team_ids))
    )
    awx_visible = (Run.source == "awx") & Run.controller_id.in_(
        select(ControllerTeam.controller_id).where(
            ControllerTeam.team_id.in_(team_ids),
            or_(
                ControllerTeam.awx_organization_id.is_(None),
                ControllerTeam.awx_organization_id == Run.awx_organization_id,
            ),
        )
    )
    return (team_owned | team_shared | awx_visible) & ~(
        (Run.source != "awx") & (Run.owner_user_id == user.id) & Run.team_id.is_(None)
    )


def _scope_base_cond(scope, user):
    """Non-team base conditions (mine/shared). Team is async -> handled by _team_scope_base."""
    if scope == "mine":
        return (Run.owner_user_id == user.id) & Run.team_id.is_(None)
    return (
        Run.id.in_(select(RunShare.run_id).where(RunShare.shared_with_user_id == user.id))
        & (Run.owner_user_id != user.id)
    )


@router.get("/filters", response_model=FacetsOut)
async def run_filters(
    user: CurrentUser, db: DbSession,
    scope: str = Query("team", pattern="^(mine|shared|team)$"),
):
    if scope == "team":
        base = await _team_scope_base(db, user)
        if base is None:
            return FacetsOut(organizations=[], templates=[], controllers=[],
                             statuses=[], launch_types=[], users=[])
    else:
        base = _scope_base_cond(scope, user)

    org_rows = (await db.execute(
        select(Run.awx_organization_id, func.max(Run.awx_organization_name))
        .where(base, Run.awx_organization_id.isnot(None))
        .group_by(Run.awx_organization_id)
        .order_by(Run.awx_organization_id)
    )).all()
    templates = (await db.execute(
        select(Run.template_name).where(base, Run.template_name.isnot(None))
        .distinct().order_by(Run.template_name)
    )).scalars().all()
    ctrl_ids = (await db.execute(
        select(Run.controller_id).where(base, Run.controller_id.isnot(None)).distinct()
    )).scalars().all()
    statuses = (await db.execute(
        select(Run.status).where(base, Run.status.isnot(None)).distinct().order_by(Run.status)
    )).scalars().all()
    launch_types = (await db.execute(
        select(Run.awx_launch_type).where(base, Run.awx_launch_type.isnot(None))
        .distinct().order_by(Run.awx_launch_type)
    )).scalars().all()
    users = (await db.execute(
        select(Run.awx_user).where(base, Run.awx_user.isnot(None)).distinct().order_by(Run.awx_user)
    )).scalars().all()

    controllers: list[FacetController] = []
    for cid in ctrl_ids:
        ctrl = await db.get(AwxController, cid)
        controllers.append(FacetController(id=str(cid), name=ctrl.name if ctrl else None))

    return FacetsOut(
        organizations=[FacetOrg(id=oid, name=oname) for oid, oname in org_rows],
        templates=list(templates),
        controllers=controllers,
        statuses=list(statuses),
        launch_types=list(launch_types),
        users=list(users),
    )


@router.get("/{run_id}", response_model=RunDetail)
async def get_run(run: VisibleRun, db: DbSession):
    controller_name = None
    if run.controller_id is not None:
        ctrl = await db.get(AwxController, run.controller_id)
        controller_name = ctrl.name if ctrl is not None else None
    return run_to_detail(run, controller_name=controller_name)


def _diff_tasks_stmt(run_id: uuid.UUID):
    """Lean column select for diffing — never pulls the heavy output/error TEXT."""
    return (
        select(Task.seq, Task.play_name, Task.name, Task.hosts, Task.duration_s)
        .where(Task.run_id == run_id)
        .order_by(Task.seq)
    )


@router.get("/{run_id}/diff", response_model=RunDiffOut)
async def get_run_diff(run: VisibleRun, user: CurrentUser, db: DbSession):
    """Diff this run against its last green baseline (same template, older, visible to U)."""
    empty = dict(newly_failing=[], fixed=[], still_failing=[], added_count=0,
                 removed_count=0, hosts_newly_unreachable=[], duration_delta_s=None,
                 slowest_changes=[])
    if run.template_name is None:
        return RunDiffOut(baseline=None, reason="no_template", **empty)
    baseline = await find_baseline(db, run, user)
    if baseline is None:
        return RunDiffOut(baseline=None, reason="no_green_run", **empty)

    controller_name = None
    if baseline.controller_id is not None:
        ctrl = await db.get(AwxController, baseline.controller_id)
        controller_name = ctrl.name if ctrl is not None else None

    cur_tasks = (await db.execute(_diff_tasks_stmt(run.id))).all()
    base_tasks = (await db.execute(_diff_tasks_stmt(baseline.id))).all()
    parts = diff_tasks(cur_tasks, base_tasks)

    duration_delta_s = None
    if run.elapsed is not None and baseline.elapsed is not None:
        duration_delta_s = run.elapsed - baseline.elapsed

    return RunDiffOut(
        baseline=run_to_card(baseline, controller_name=controller_name),
        reason=None,
        hosts_newly_unreachable=recap_newly_unreachable(run.recap, baseline.recap),
        duration_delta_s=duration_delta_s,
        **parts,
    )


@router.get("/{run_id}/tasks", response_model=list[TaskLean])
async def list_tasks(run: VisibleRun, db: DbSession):
    # Lean list: select only lean columns so the heavy output/error TEXT never
    # crosses the wire (the lean/full split exists to avoid it).
    rows = (await db.execute(
        select(
            Task.seq, Task.play_name, Task.role, Task.name, Task.status,
            Task.hosts, Task.items_count, Task.line_no, Task.duration_s,
        ).where(Task.run_id == run.id).order_by(Task.seq)
    )).all()
    return [task_to_lean(r) for r in rows]


@router.get("/{run_id}/tasks/{seq}", response_model=TaskFull)
async def get_task(run: VisibleRun, seq: int, db: DbSession):
    t = await db.scalar(select(Task).where(Task.run_id == run.id, Task.seq == seq))
    if t is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Task not found")
    return task_to_full(t)


@router.get("/{run_id}/tasks/{seq}/kb")
async def get_task_kb(run: VisibleRun, seq: int, user: CurrentUser, db: DbSession) -> KbSuggestionOut | None:
    """The drawer 'Known issue' card: the precomputed match for this task, or null.

    Reads precomputed kb_occurrences only (M5-D2, no live matching). The matched
    signature must be visible to U (global ∪ U-team); an occurrence pointing at a
    non-visible signature yields null (no leak). Run visibility is the VisibleRun gate.
    """
    from app.api.kb import signature_to_out  # local import avoids any potential circular import

    team_ids = await my_team_ids(db, user)
    sig_visible = kb_visibility_cond(team_ids)
    row = (await db.execute(
        select(KbOccurrence, KbSignature)
        .join(KbSignature, KbSignature.id == KbOccurrence.signature_id)
        .where(KbOccurrence.run_id == run.id, KbOccurrence.task_seq == seq, sig_visible)
        .order_by(KbOccurrence.matched_at.desc())
        .limit(1)
    )).first()
    if row is None:
        return None
    _occ, sig = row

    # exact/score hint: re-extract this task's signature (pure) and compare keys.
    task = await db.scalar(select(Task).where(Task.run_id == run.id, Task.seq == seq))
    extracted = extract_signature(task.error) if task is not None else None
    exact = extracted is not None and extracted.signature_key == sig.signature_key
    if exact:
        score = 1.0
    elif extracted is not None:
        # Compute real pg_trgm similarity between the extracted representative_text
        # and the matched signature's representative_text (clamp to [0.0, 1.0]).
        raw_score = await db.scalar(
            select(func.similarity(extracted.representative_text, sig.representative_text))
        )
        score = float(raw_score) if raw_score is not None else 0.0
    else:
        score = 0.0

    n = await visible_occurrence_count(db, sig.id, user)
    return KbSuggestionOut(
        signature=signature_to_out(sig, occurrence_count=n),
        exact=exact,
        score=score,
    )


@router.get("/{run_id}/raw", response_class=PlainTextResponse)
async def get_raw(run: VisibleRun, db: DbSession):
    content = await db.scalar(select(RunRaw.content).where(RunRaw.run_id == run.id))
    if content is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Raw log not found")
    return PlainTextResponse(content)


# ---------------------------------------------------------------------------
# Run Path Explorer — /tree, /nodes/{node_id}/results, /inputs
# ---------------------------------------------------------------------------

def _sub_for(n: RunNode) -> str | None:
    if n.node_type == "loop":
        return f"loop · {n.item_count} items"
    if n.node_type in ("role", "include", "block"):
        return f"{n.node_type} · {n.child_count} tasks"
    return None


def _enter_to(n: RunNode) -> EnterToOut | None:
    if n.node_type == "loop":
        return EnterToOut(type="loop", id=n.node_id)
    if n.node_type in ("role", "include", "block") and n.child_count > 0:
        return EnterToOut(type="container", id=n.node_id)
    return None


def _node_out(n: RunNode) -> PathNodeOut:
    return PathNodeOut(
        id=n.node_id, type=n.node_type, label=n.name, sub=_sub_for(n), status=n.status,
        action=n.action, host_count=n.host_count or None, item_count=n.item_count or None,
        has_failures=(n.status in ("failed", "unreachable")),
        is_conditional=n.is_conditional, condition=n.when_expr, branch=None,
        enter_to=_enter_to(n), child_count=(n.child_count or None),
        duration_s=n.duration_s, task_path=n.task_path,
    )


def _linear_edges(nodes: list[RunNode]) -> list[PathEdgeOut]:
    ordered = sorted(nodes, key=lambda n: n.counter)
    return [PathEdgeOut(from_=ordered[i].node_id, to=ordered[i + 1].node_id, branch=None)
            for i in range(len(ordered) - 1)]


@router.get("/{run_id}/tree", response_model=PathTreeOut,
            response_model_by_alias=True, response_model_exclude_none=True)
async def get_run_tree(run: VisibleRun, db: DbSession,
                       root: str | None = Query(None), iter: int = Query(0, ge=0)):
    all_nodes = (await db.execute(
        select(RunNode).where(RunNode.run_id == run.id).order_by(RunNode.counter)
    )).scalars().all()
    by_id = {n.node_id: n for n in all_nodes}

    # loop view: synthesize loopRoot -> item -> task -> result from the loop node + its iter-th result
    if root is not None and (loop := by_id.get(root)) is not None and loop.node_type == "loop":
        results = (await db.execute(
            select(RunNodeResult).where(RunNodeResult.run_id == run.id,
                                        RunNodeResult.node_id == root,
                                        RunNodeResult.item_index.isnot(None))
            .order_by(RunNodeResult.item_index)
        )).scalars().all()
        sel = results[iter] if 0 <= iter < len(results) else None
        val = sel.item_value if sel is not None else None
        st = sel.status if sel is not None else loop.status
        nodes = [
            PathNodeOut(id="loopRoot", type="loop", label=loop.name, sub=_sub_for(loop),
                        status=loop.status, item_count=loop.item_count or None),
            PathNodeOut(id="item", type="item", label=f'= "{val}"' if val is not None else "item",
                        sub=f"iteration {iter + 1}", status="ok"),
            PathNodeOut(id="task", type="task", label=loop.action or loop.name,
                        sub=(f'name="{val}"' if val is not None else None), status=st,
                        action=loop.action, host_count=loop.host_count or None,
                        task_path=loop.task_path),
            PathNodeOut(id="result", type="result", label="result", sub=st, status=st),
        ]
        edges = [PathEdgeOut(from_="loopRoot", to="item", branch=None),
                 PathEdgeOut(from_="item", to="task", branch=None),
                 PathEdgeOut(from_="task", to="result", branch=None)]
        return PathTreeOut(run_id=str(run.id), view=PathViewOut(type="loop", id=root),
                           nodes=nodes, edges=edges)

    # container view: children of `root`
    if root is not None and root in by_id:
        kids = [n for n in all_nodes if n.parent_node_id == root]
        return PathTreeOut(run_id=str(run.id), view=PathViewOut(type="container", id=root),
                           nodes=[_node_out(n) for n in kids], edges=_linear_edges(kids))

    # main view: children of the run root; if exactly one play, descend into it (flat task band)
    roots = [n for n in all_nodes if n.parent_node_id is None]  # the synthetic playbook root(s)
    top = [n for n in all_nodes if n.parent_node_id in {r.node_id for r in roots}]
    plays = [n for n in top if n.node_type == "play"]
    if len(plays) == 1:
        top = [n for n in all_nodes if n.parent_node_id == plays[0].node_id]
    return PathTreeOut(run_id=str(run.id), view=PathViewOut(type="main"),
                       nodes=[_node_out(n) for n in top], edges=_linear_edges(top))


@router.get("/{run_id}/nodes/{node_id}/results", response_model=NodeResultsPageOut)
async def get_node_results(run: VisibleRun, node_id: str, db: DbSession,
                           host: str | None = Query(None), status: str | None = Query(None),
                           offset: int = Query(0, ge=0), limit: int = Query(100, ge=1, le=500)):
    base = select(RunNodeResult).where(RunNodeResult.run_id == run.id,
                                       RunNodeResult.node_id == node_id)
    if host:
        base = base.where(RunNodeResult.host == host)
    if status:
        base = base.where(RunNodeResult.status == status)
    total = await db.scalar(select(func.count()).select_from(base.subquery()))
    rows = (await db.execute(
        base.order_by(nulls_last(RunNodeResult.item_index), RunNodeResult.host)
        .offset(offset).limit(limit)
    )).scalars().all()

    def _out(r: RunNodeResult) -> NodeResultOut:
        res = r.result or {}
        output = res.get("msg") or res.get("stdout") or (json.dumps(res) if res else None)
        return NodeResultOut(host=r.host, item_index=r.item_index, item_value=r.item_value,
                             status=r.status, changed=r.changed, output=output,
                             skip_reason=r.skip_reason or r.false_condition, duration_s=r.duration_s)

    return NodeResultsPageOut(results=[_out(r) for r in rows], total=total or 0)


@router.get("/{run_id}/inputs", response_model=RunInputsOut)
async def get_run_inputs(run: VisibleRun):
    return RunInputsOut(
        extra_vars=run.extra_vars or {}, survey=run.survey, limit=run.awx_limit,
        scm_revision=run.scm_revision, project_id=run.project_id, project_name=run.project_name,
    )


@router.delete("/{run_id}", status_code=204)
async def delete_run(run: OwnedRun, request: Request, db: DbSession, user: GatedUser):
    await db.delete(run)  # cascades tasks + run_raw via ondelete=CASCADE
    await write_audit(db, action="run_delete", actor_id=user.id,
                      target_type="run", target_id=str(run.id), ip=client_ip(request))
    await db.commit()
    return None


@router.post("/{run_id}/shares", status_code=201, response_model=ShareOut)
async def create_share(
    run: OwnedRun, payload: ShareCreate, request: Request, db: DbSession, user: GatedUser,
):
    # Exactly one target (XOR) — DB CHECK also guards, but validate up front for a clean 422.
    if (payload.user_id is None) == (payload.team_id is None):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT,
                            detail="Provide exactly one of user_id or team_id")

    target_user: User | None = None
    target_team: Team | None = None
    if payload.user_id is not None:
        try:
            uid = uuid.UUID(payload.user_id)
        except ValueError:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail="Invalid user_id")
        target_user = await db.get(User, uid)
        if target_user is None:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail="Unknown user")
        share = RunShare(run_id=run.id, shared_with_user_id=uid, shared_by_user_id=user.id)
    else:
        target_team = await resolve_team_or_422(db, payload.team_id)
        share = RunShare(run_id=run.id, shared_with_team_id=target_team.id, shared_by_user_id=user.id)

    db.add(share)
    try:
        await db.flush()  # surfaces the partial-unique violation on a duplicate share
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, detail="Already shared with this target")

    await create_share_notifications(db, run=run, share=share, actor_id=user.id)
    await write_audit(db, action="run_share", actor_id=user.id,
                      target_type="run_share", target_id=str(share.id), ip=client_ip(request),
                      metadata={"run_id": str(run.id)})
    await db.commit()
    return share_to_out(share, user=target_user, team=target_team)


@router.get("/{run_id}/shares", response_model=list[ShareOut])
async def list_shares(run: OwnedRun, db: DbSession):
    shares = (await db.execute(
        select(RunShare).where(RunShare.run_id == run.id).order_by(RunShare.created_at)
    )).scalars().all()
    out: list[ShareOut] = []
    for s in shares:
        u = await db.get(User, s.shared_with_user_id) if s.shared_with_user_id else None
        t = await db.get(Team, s.shared_with_team_id) if s.shared_with_team_id else None
        out.append(share_to_out(s, user=u, team=t))
    return out


@router.delete("/{run_id}/shares/{share_id}", status_code=204)
async def delete_share(
    run: OwnedRun, share_id: uuid.UUID, request: Request, db: DbSession, user: GatedUser,
):
    share = await db.scalar(
        select(RunShare).where(RunShare.id == share_id, RunShare.run_id == run.id)
    )
    if share is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Share not found")
    await db.delete(share)
    await write_audit(db, action="run_unshare", actor_id=user.id,
                      target_type="run_share", target_id=str(share_id), ip=client_ip(request),
                      metadata={"run_id": str(run.id)})
    await db.commit()
    return None


@router.get("/{run_id}/annotations", response_model=list[AnnotationOut])
async def list_annotations(run: VisibleRun, db: DbSession):
    rows = (await db.execute(
        select(Annotation, User.display_name)
        .join(User, User.id == Annotation.author_user_id)
        .where(Annotation.run_id == run.id)
        .order_by(Annotation.created_at)
    )).all()
    return [annotation_to_out(a, author_name=name) for a, name in rows]


@router.post("/{run_id}/tasks/{seq}/annotations", status_code=201, response_model=AnnotationOut)
async def create_annotation(
    run: VisibleRun, seq: int, payload: AnnotationCreate,
    request: Request, db: DbSession, user: GatedUser,
):
    await _require_task(db, run.id, seq)
    tags = validate_tags(payload.tags)
    links = validate_links(payload.links)
    # Reject a fully-empty annotation (no note, no tags, no links) — it carries no content.
    # A tag-only or link-only annotation is still allowed.
    if not payload.note.strip() and not tags and not links:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT,
                            detail="Annotation must have a note, a tag, or a link")
    a = Annotation(
        run_id=run.id, task_seq=seq, author_user_id=user.id,
        note=payload.note, tags=tags, links=links,
    )
    db.add(a)
    await write_audit(db, action="annotation_create", actor_id=user.id,
                      target_type="run", target_id=str(run.id), ip=client_ip(request))
    await db.commit()
    await db.refresh(a)
    return annotation_to_out(a, author_name=user.display_name)


# ---------------------------------------------------------------------------
# C1/C2 — Comment thread (read + create)
# ---------------------------------------------------------------------------

async def _name_map(db: DbSession, ids: set[uuid.UUID]) -> dict[uuid.UUID, str]:
    """Batch-resolve {user_id: display_name} in ONE query (avoids N+1 across a thread)."""
    if not ids:
        return {}
    rows = (await db.execute(
        select(User.id, User.display_name).where(User.id.in_(ids))
    )).all()
    return {uid: name for uid, name in rows}


async def _comment_out_with_names(c: Comment, db: DbSession) -> CommentOut:
    """Single-comment response builder: one batch query for the author name."""
    names = await _name_map(db, {c.author_user_id})
    author_name = names.get(c.author_user_id, "(unknown)")
    return comment_to_out(c, author_name=author_name)


@router.get("/{run_id}/tasks/{seq}/comments", response_model=list[CommentOut])
async def list_comments(run: VisibleRun, seq: int, db: DbSession):
    rows = (await db.execute(
        select(Comment)
        .where(Comment.run_id == run.id, Comment.task_seq == seq)
        .order_by(Comment.created_at)
    )).scalars().all()
    # Batch ALL author ids across the whole thread into ONE lookup (no N+1).
    names = await _name_map(db, {c.author_user_id for c in rows})
    return [
        comment_to_out(c, author_name=names.get(c.author_user_id, "(unknown)"))
        for c in rows
    ]


@router.post("/{run_id}/tasks/{seq}/comments", status_code=201, response_model=CommentOut)
async def create_comment(
    run: VisibleRun, seq: int, payload: CommentCreate,
    request: Request, db: DbSession, user: GatedUser,
):
    await _require_task(db, run.id, seq)
    # Parse + validate client-supplied ids defensively (malformed -> 422, never 500).
    # Enforce cross-run thread integrity BEFORE constructing the Comment so a foreign id
    # can't graft a thread across runs or act as an existence oracle.
    parent_uuid: uuid.UUID | None = None
    annotation_uuid: uuid.UUID | None = None

    if payload.parent_id is not None:
        try:
            parent_uuid = uuid.UUID(payload.parent_id)
        except (ValueError, AttributeError):
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail="Invalid parent_id")
        parent = await db.get(Comment, parent_uuid)
        # parent must be on THIS run + THIS task, be a root (single-level threading, M3-D6),
        # and not be soft-deleted (can't reply to a tombstone).
        if (
            parent is None
            or parent.run_id != run.id
            or parent.task_seq != seq
            or parent.parent_id is not None
            or parent.deleted_at is not None
        ):
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail="Invalid parent_id")

    if payload.annotation_id is not None:
        try:
            annotation_uuid = uuid.UUID(payload.annotation_id)
        except (ValueError, AttributeError):
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail="Invalid annotation_id")
        annotation = await db.get(Annotation, annotation_uuid)
        # Must belong to THIS run AND THIS task — a comment thread is per-task, so it may not
        # reference an annotation from another task (even within the same run).
        if annotation is None or annotation.run_id != run.id or annotation.task_seq != seq:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail="Invalid annotation_id")

    survivors = await resolve_visible_mentions(db, run, payload.mentions)
    mention_ids = [uid for uid, _name in survivors]

    c = Comment(
        run_id=run.id,
        task_seq=seq,
        annotation_id=annotation_uuid,
        parent_id=parent_uuid,
        author_user_id=user.id,
        body=payload.body,
        mentions=mention_ids,
    )
    db.add(c)
    await db.flush()  # populate c.id and c.run_id before notification fan-out
    await create_mention_notifications(
        db, comment=c, mention_ids=c.mentions, actor_id=user.id
    )
    await write_audit(
        db, action="comment_create", actor_id=user.id,
        target_type="run", target_id=str(run.id), ip=client_ip(request),
    )
    await db.commit()
    await db.refresh(c)
    return await _comment_out_with_names(c, db)


# ---------------------------------------------------------------------------
# M1 — Mention autocomplete (run-visible users matching q)
# ---------------------------------------------------------------------------

@router.get("/{run_id}/mentionable", response_model=list[MentionableUser])
async def list_mentionable(run: VisibleRun, db: DbSession, q: str = "", limit: int = 20):
    """Return users who can see this run, optionally filtered by display_name/email substring.

    Visible-user set: owner ∪ direct-share targets ∪ members of the owning team
    ∪ members of any team the run is shared with. Restricting to this set prevents
    @mention from leaking non-visible users (M3-D9 / A1 invariant).
    """
    user_ids: set[uuid.UUID] = {run.owner_user_id}

    # Direct-share targets (user shares)
    user_ids |= set((await db.execute(
        select(RunShare.shared_with_user_id).where(
            RunShare.run_id == run.id, RunShare.shared_with_user_id.isnot(None))
    )).scalars().all())

    # Collect all team ids: owning team + teams the run is shared with
    team_ids: set[uuid.UUID] = set()
    if run.team_id is not None:
        team_ids.add(run.team_id)
    team_ids |= set((await db.execute(
        select(RunShare.shared_with_team_id).where(
            RunShare.run_id == run.id, RunShare.shared_with_team_id.isnot(None))
    )).scalars().all())

    # Members of all those teams
    if team_ids:
        user_ids |= set((await db.execute(
            select(TeamMember.user_id).where(TeamMember.team_id.in_(team_ids))
        )).scalars().all())

    # AWX runs are also visible to members of the controller's assigned teams (org-aware) —
    # mirror visibility path #5 so @mention can reach everyone who can actually see the run.
    if run.source == "awx" and run.controller_id is not None:
        ctrl_team_ids = select(ControllerTeam.team_id).where(
            ControllerTeam.controller_id == run.controller_id,
            or_(
                ControllerTeam.awx_organization_id.is_(None),
                ControllerTeam.awx_organization_id == run.awx_organization_id,
            ),
        )
        user_ids |= set((await db.execute(
            select(TeamMember.user_id).where(TeamMember.team_id.in_(ctrl_team_ids))
        )).scalars().all())

    stmt = select(User).where(User.id.in_(user_ids), User.is_active.is_(True))
    if q:
        like = f"%{q}%"
        stmt = stmt.where(or_(User.display_name.ilike(like), User.email.ilike(like)))
    stmt = stmt.order_by(User.display_name).limit(limit)
    rows = (await db.execute(stmt)).scalars().all()
    return [
        MentionableUser(
            id=str(u.id), display_name=u.display_name, email=u.email,
            initials=u.initials, avatar_color=u.avatar_color,
        )
        for u in rows
    ]
