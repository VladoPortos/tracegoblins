from __future__ import annotations

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.projects_schemas import ProjectOut
from app.models import AwxController, Project, Run


def linked_runs_cond(project: Project):
    """The run↔project auto-link predicate (no FK; a join on controller + AWX project id)."""
    return and_(Run.controller_id == project.controller_id,
                Run.project_id == project.awx_project_id)


async def linked_run_count(db: AsyncSession, project: Project) -> int:
    return await db.scalar(
        select(func.count()).select_from(Run).where(linked_runs_cond(project))
    ) or 0


async def project_to_out(db: AsyncSession, project: Project) -> ProjectOut:
    """Serialize a project for the detail API. The git secret is NEVER placed on the model —
    only a `has_git_secret` boolean. `effective_git_url` = coalesce(override, scm_url)."""
    ctrl = await db.get(AwxController, project.controller_id)
    return ProjectOut(
        id=str(project.id),
        controller_id=str(project.controller_id),
        controller_name=ctrl.name if ctrl is not None else None,
        awx_project_id=project.awx_project_id,
        name=project.name,
        scm_type=project.scm_type,
        scm_url=project.scm_url,
        scm_branch=project.scm_branch,
        scm_revision=project.scm_revision,
        description=project.description,
        organization_id=project.organization_id,
        organization_name=project.organization_name,
        status=project.status,
        effective_git_url=(
            project.git_url_override if project.git_url_override is not None
            else project.scm_url
        ),
        git_url_override=project.git_url_override,
        git_auth_type=project.git_auth_type,
        git_username=project.git_username,
        has_git_secret=project.git_secret_encrypted is not None,
        last_clone_at=project.last_clone_at,
        last_clone_error=project.last_clone_error,
        clone_size_bytes=project.clone_size_bytes,
        linked_run_count=await linked_run_count(db, project),
        created_at=project.created_at,
        updated_at=project.updated_at,
    )
