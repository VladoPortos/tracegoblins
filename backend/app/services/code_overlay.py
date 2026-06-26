"""On-demand source overlay for a run node — joins M1 run nodes to M2 git blobs.

No new tables: everything is derived from run_nodes / run_node_results / runs.scm_revision
and the project's bare clone. Run-visibility is enforced by the caller (VisibleRun).
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.path_schemas import NodeSourceOut, ResolvedValueOut  # noqa: F401 (ResolvedValueOut exported for future tasks)
from app.core.config import settings
from app.models import Project, Run, RunNode, RunNodeResult
from app.projects.git import GitError, read_blob, revision_exists
from app.projects.storage import project_repo_path


def split_task_path(task_path: str | None) -> tuple[str, int] | None:
    """'roles/app/tasks/main.yml:42' -> ('roles/app/tasks/main.yml', 42); None if no line."""
    if not task_path or ":" not in task_path:
        return None
    path, _, line = task_path.rpartition(":")
    if not path or not line.isdigit():
        return None
    return path, int(line)


async def resolve_project_for_run(db: AsyncSession, run: Run) -> Project | None:
    """The run↔project auto-link (no FK): same controller + AWX project id."""
    if run.controller_id is None or run.project_id is None:
        return None
    return await db.scalar(select(Project).where(
        Project.controller_id == run.controller_id,
        Project.awx_project_id == run.project_id,
    ))


async def _executed_lines_for_file(db: AsyncSession, run_id, file: str) -> list[int]:
    rows = (await db.execute(
        select(RunNode.task_path).where(RunNode.run_id == run_id, RunNode.task_path.isnot(None))
    )).scalars().all()
    lines = {sp[1] for tp in rows if (sp := split_task_path(tp)) and sp[0] == file}
    return sorted(lines)


async def build_node_source(db: AsyncSession, run: Run, node: RunNode) -> NodeSourceOut:
    base = dict(project_id=None, path=None, ref=run.scm_revision, content=None,
                focus_line=None, executed_lines=[], never_run_lines=[], resolved=[], hosts=[])
    sp = split_task_path(node.task_path)
    if sp is None:
        return NodeSourceOut(**base, unavailable="no_path")
    file, line = sp
    base.update(path=file, focus_line=line)

    proj = await resolve_project_for_run(db, run)
    if proj is None:
        return NodeSourceOut(**base, unavailable="not_linked")
    base.update(project_id=str(proj.id))
    repo = project_repo_path(proj.id)
    if proj.status != "cloned" or not repo.exists():
        return NodeSourceOut(**base, unavailable="not_cloned")
    if not run.scm_revision or not await revision_exists(repo, run.scm_revision):
        return NodeSourceOut(**base, unavailable="revision_missing")
    try:
        blob = await read_blob(repo, run.scm_revision, file, settings.project_blob_max_bytes)
    except GitError:
        return NodeSourceOut(**base, unavailable="revision_missing")
    if blob.too_large:
        return NodeSourceOut(**base, unavailable="too_large")
    if blob.binary or blob.text is None:
        return NodeSourceOut(**base, unavailable="binary")

    base.update(content=blob.text,
                executed_lines=await _executed_lines_for_file(db, run.id, file))
    return NodeSourceOut(**base)
