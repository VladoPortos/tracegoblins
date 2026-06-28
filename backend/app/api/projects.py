from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, Query, Request, UploadFile, status
from sqlalchemy import and_, func, select, tuple_

from app.api.deps import AdminUser, CurrentUser, DbSession, require_password_current
from app.api.http_utils import client_ip
from app.api.projects_schemas import (
    UNCHANGED_SECRET, BlobOut, ProjectGitIn, ProjectListItem, ProjectListOut, ProjectOut,
    TreeEntryOut, TreeOut,
)
from app.awx.client import AwxClient, AwxError
from app.awx.projects_sync import sync_projects
from app.core.config import settings
from app.core.crypto import TokenCryptoError, decrypt_token, encrypt_token
from app.models import AwxController, ControllerTeam, Project, Run
from app.projects import git as gitmod
from app.projects import uploads as uploadsmod
from app.projects.git import is_clonable_git_url
from app.projects.storage import project_repo_path, project_uploads_path
from app.projects.worker import run_clone
from app.services.audit import write_audit
from app.services.projects_query import linked_runs_cond, project_to_out
from app.services.runs_query import run_to_card
from app.services.visibility import is_project_visible, my_team_ids, project_visible_cond

router = APIRouter(
    prefix="/api/projects",
    tags=["projects"],
    dependencies=[Depends(require_password_current)],
)


async def get_visible_project(project_id: uuid.UUID, user: CurrentUser, db: DbSession) -> Project:
    """Return the project iff U can see it (controller-team, org-aware); else 404 (never 403)."""
    project = await db.get(Project, project_id)
    if project is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Project not found")
    if not await is_project_visible(db, project, user):
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Project not found")  # 404, never 403
    return project


VisibleProject = Annotated[Project, Depends(get_visible_project)]


@router.get("", response_model=ProjectListOut)
async def list_projects_api(
    user: CurrentUser, db: DbSession,
    controller: str | None = Query(None),
    q: str | None = Query(None),
    offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=200),
):
    cond = await project_visible_cond(db, user)
    if controller is not None:
        try:
            cond = and_(cond, Project.controller_id == uuid.UUID(controller))
        except ValueError:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Invalid controller")
    if q:
        cond = and_(cond, Project.name.ilike(f"%{q}%"))

    total = await db.scalar(select(func.count()).select_from(Project).where(cond)) or 0
    rows = (await db.execute(
        select(Project).where(cond).order_by(Project.name).offset(offset).limit(limit)
    )).scalars().all()

    ctrl_ids = {p.controller_id for p in rows}
    names: dict[uuid.UUID, str] = {}
    if ctrl_ids:
        names = {c.id: c.name for c in (await db.scalars(
            select(AwxController).where(AwxController.id.in_(ctrl_ids))
        )).all()}

    # Linked-run counts for the whole page in ONE grouped query, not one COUNT(*) per row (PERF1).
    pairs = {(p.controller_id, p.awx_project_id) for p in rows}
    count_map: dict[tuple, int] = {}
    if pairs:
        count_map = {
            (cid, pid): n for cid, pid, n in (await db.execute(
                select(Run.controller_id, Run.project_id, func.count())
                .where(tuple_(Run.controller_id, Run.project_id).in_(list(pairs)))
                .group_by(Run.controller_id, Run.project_id)
            )).all()
        }

    items = [
        ProjectListItem(
            id=str(p.id), name=p.name, controller_id=str(p.controller_id),
            controller_name=names.get(p.controller_id), scm_type=p.scm_type,
            scm_branch=p.scm_branch, status=p.status,
            linked_run_count=count_map.get((p.controller_id, p.awx_project_id), 0),
        )
        for p in rows
    ]
    return ProjectListOut(items=items, total=total)


@router.get("/{project_id}", response_model=ProjectOut)
async def get_project_api(project: VisibleProject, db: DbSession):
    return await project_to_out(db, project)


@router.get("/{project_id}/runs")
async def get_project_runs(
    project: VisibleProject, db: DbSession,
    offset: int = Query(0, ge=0), limit: int = Query(20, ge=1, le=100),
):
    cond = linked_runs_cond(project)
    total = await db.scalar(select(func.count()).select_from(Run).where(cond)) or 0
    rows = (await db.execute(
        select(Run).where(cond)
        .order_by(func.coalesce(Run.launched_at, Run.log_time, Run.created_at).desc(), Run.id.desc())
        .offset(offset).limit(limit)
    )).scalars().all()
    return {"items": [run_to_card(r) for r in rows], "total": total}


@router.put("/{project_id}/git", response_model=ProjectOut)
async def set_project_git(
    project: VisibleProject, payload: ProjectGitIn,
    request: Request, db: DbSession, user: AdminUser,
):
    """Admin: link/update the project's git source + write-only secret. Sets status=pending."""
    if payload.git_url_override:
        if not is_clonable_git_url(payload.git_url_override):
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT,
                                detail="git_url_override must be an https URL (no SSH/http)")
        project.git_url_override = payload.git_url_override.strip()
    else:
        project.git_url_override = None

    project.git_auth_type = payload.auth_type
    project.git_username = payload.username or None

    # write-only secret: sentinel/omitted → leave intact; "" → clear; non-empty value → (re)encrypt.
    if payload.secret == UNCHANGED_SECRET:
        pass  # leave git_secret_encrypted untouched
    elif payload.secret == "":
        project.git_secret_encrypted = None
    elif payload.secret is not None:
        project.git_secret_encrypted = encrypt_token(payload.secret)

    project.status = "pending"
    await write_audit(db, action="project_git_link", actor_id=user.id,
                      target_type="project", target_id=str(project.id), ip=client_ip(request),
                      metadata={"auth_type": payload.auth_type, "secret": "***redacted***"})
    await db.commit()
    await db.refresh(project)
    return await project_to_out(db, project)


@router.post("/{project_id}/clone", status_code=202)
async def clone_project(
    project: VisibleProject, background: BackgroundTasks,
    request: Request, db: DbSession, user: AdminUser,
):
    """Admin: enqueue a background clone/fetch. The per-project advisory lock dedupes."""
    if project.scm_type != "git":
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT,
                            detail="Only scm_type='git' projects can be cloned")
    effective_url = project.git_url_override or project.scm_url
    if not is_clonable_git_url(effective_url):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT,
                            detail="No https git URL — set an https override first")
    project.status = "pending"
    await write_audit(db, action="project_clone", actor_id=user.id,
                      target_type="project", target_id=str(project.id), ip=client_ip(request))
    await db.commit()
    background.add_task(run_clone, str(project.id))
    return {"status": "started"}


@router.post("/{project_id}/refresh-mirror", response_model=ProjectOut)
async def refresh_mirror(
    project: VisibleProject, request: Request, db: DbSession, user: CurrentUser,
):
    """Member: re-pull AWX metadata for this project's controller (read-only). Member must be in
    a team assigned to the controller (admin role alone is not a path — mirrors sync_now)."""
    assigned = set((await db.execute(
        select(ControllerTeam.team_id).where(ControllerTeam.controller_id == project.controller_id)
    )).scalars().all())
    mine = await my_team_ids(db, user)
    # Defense-in-depth: unreachable for a visible project (VisibleProject already requires
    # controller-team membership, a subset of assigned&mine) — kept in case the dep changes.
    if not (assigned & mine):
        raise HTTPException(status.HTTP_403_FORBIDDEN,
                            detail="Not a member of any team assigned to this controller")

    controller = await db.get(AwxController, project.controller_id)
    await write_audit(db, action="project_refresh_mirror", actor_id=user.id,
                      target_type="project", target_id=str(project.id), ip=client_ip(request))
    await db.commit()
    try:
        token = decrypt_token(controller.auth_token_encrypted)
        async with AwxClient(controller.base_url, token, controller.verify_ssl) as client:
            await sync_projects(db, controller, client)
    except (AwxError, TokenCryptoError) as e:
        # an undecryptable stored token is a config error, not a 500 (ERR1) — mirror sync handling
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, detail=f"AWX refresh failed: {e}")
    await db.refresh(project)
    return await project_to_out(db, project)


@router.get("/{project_id}/tree", response_model=TreeOut)
async def get_project_tree(
    project: VisibleProject, db: DbSession,
    ref: str = Query("HEAD"), path: str = Query(""),
):
    if ref == "uploads":
        try:
            entries = uploadsmod.list_uploads_tree(project_uploads_path(project.id), path)
        except uploadsmod.UploadError:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail="Invalid path")
        return TreeOut(ref=ref, path=path,
                       entries=[TreeEntryOut(name=e.name, type=e.type, size=e.size, mode=e.mode)
                                for e in entries])

    repo = project_repo_path(project.id)
    if project.status != "cloned" or not repo.exists():
        raise HTTPException(status.HTTP_409_CONFLICT, detail="Project source not cloned yet")
    if not await gitmod.revision_exists(repo, ref):
        raise HTTPException(status.HTTP_409_CONFLICT,
                            detail="Revision not in clone — refresh source")
    try:
        entries = await gitmod.list_tree(repo, ref, path)
    except gitmod.GitError:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail="Invalid ref or path")
    return TreeOut(ref=ref, path=path,
                   entries=[TreeEntryOut(name=e.name, type=e.type, size=e.size, mode=e.mode)
                            for e in entries])


@router.get("/{project_id}/blob", response_model=BlobOut)
async def get_project_blob(
    project: VisibleProject, db: DbSession,
    ref: str = Query("HEAD"), path: str = Query(...),
):
    cap = settings.project_blob_max_bytes
    if ref == "uploads":
        try:
            blob = uploadsmod.read_upload_blob(project_uploads_path(project.id), path, cap)
        except uploadsmod.UploadError:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail="File not found")
        return BlobOut(ref=ref, path=path, content=blob.text, size=blob.size,
                       too_large=blob.too_large, binary=blob.binary)

    repo = project_repo_path(project.id)
    if project.status != "cloned" or not repo.exists():
        raise HTTPException(status.HTTP_409_CONFLICT, detail="Project source not cloned yet")
    if not await gitmod.revision_exists(repo, ref):
        raise HTTPException(status.HTTP_409_CONFLICT,
                            detail="Revision not in clone — refresh source")
    try:
        blob = await gitmod.read_blob(repo, ref, path, cap)
    except gitmod.GitError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="File not found at revision")
    return BlobOut(ref=ref, path=path, content=blob.text, size=blob.size,
                   too_large=blob.too_large, binary=blob.binary)


@router.post("/{project_id}/uploads", status_code=201)
async def upload_files(
    project: VisibleProject, request: Request, db: DbSession, user: AdminUser,
    files: list[UploadFile] = File(...), paths: list[str] = Form(...),
):
    """Admin: drop-zone upload of files+folders. Each file is paired with its relative path
    (webkitRelativePath) by list index; traversal + size/count caps enforced."""
    if len(files) != len(paths):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT,
                            detail="files and paths length mismatch")
    payload: list[tuple[str, bytes]] = []
    total = 0
    for f, rel in zip(files, paths):
        data = await f.read()
        total += len(data)
        if total > settings.project_upload_max_bytes:
            raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, detail="Upload too large")
        payload.append((rel, data))
    try:
        n = uploadsmod.save_uploads(
            project_uploads_path(project.id), payload,
            max_bytes=settings.project_upload_max_bytes,
            max_files=settings.project_upload_max_files,
        )
    except uploadsmod.UploadError as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(e))
    await write_audit(db, action="project_upload", actor_id=user.id,
                      target_type="project", target_id=str(project.id), ip=client_ip(request),
                      metadata={"files": n})
    await db.commit()
    return {"uploaded": n}
