from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import and_, func, select

from app.api.deps import CurrentUser, DbSession, require_password_current
from app.api.projects_schemas import ProjectListItem, ProjectListOut, ProjectOut
from app.models import AwxController, Project, Run
from app.services.projects_query import (
    linked_run_count, linked_runs_cond, project_to_out,
)
from app.services.runs_query import run_to_card
from app.services.visibility import is_project_visible, project_visible_cond

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

    items = [
        ProjectListItem(
            id=str(p.id), name=p.name, controller_id=str(p.controller_id),
            controller_name=names.get(p.controller_id), scm_type=p.scm_type,
            scm_branch=p.scm_branch, status=p.status,
            linked_run_count=await linked_run_count(db, p),
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
