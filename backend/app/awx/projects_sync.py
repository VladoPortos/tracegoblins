from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.awx.client import AwxClient
from app.models import AwxController, Project
from app.services.audit import write_audit

logger = logging.getLogger(__name__)


async def sync_projects(db: AsyncSession, controller: AwxController, client: AwxClient) -> int:
    """Mirror AWX project metadata into `projects` for one controller.

    Upserts by (controller_id, awx_project_id): inserts new rows (status='unlinked') and
    refreshes ONLY the AWX-mirrored columns on existing rows — the local git-link / creds /
    clone-status fields are never overwritten on re-sync. Projects that disappear from AWX are
    kept (they may still own a clone + linked runs). Commits its own unit of work + one audit
    row; the caller treats it as best-effort.
    """
    summaries = await client.list_projects()
    existing = {
        p.awx_project_id: p
        for p in (await db.scalars(
            select(Project).where(Project.controller_id == controller.id)
        )).all()
    }
    for s in summaries:
        p = existing.get(s.id)
        if p is None:
            db.add(Project(
                controller_id=controller.id, awx_project_id=s.id, name=s.name,
                scm_type=s.scm_type, scm_url=s.scm_url, scm_branch=s.scm_branch,
                scm_revision=s.scm_revision, description=s.description,
                organization_id=s.organization_id, organization_name=s.organization_name,
                status="unlinked",
            ))
        else:
            p.name = s.name
            p.scm_type = s.scm_type
            p.scm_url = s.scm_url
            p.scm_branch = s.scm_branch
            p.scm_revision = s.scm_revision
            p.description = s.description
            p.organization_id = s.organization_id
            p.organization_name = s.organization_name
            # status / git_* / last_clone_* / clone_size_bytes are LOCAL — never touched here.
    await write_audit(db, action="projects_mirror", target_type="awx_controller",
                      target_id=str(controller.id), metadata={"count": len(summaries)})
    await db.commit()
    return len(summaries)
