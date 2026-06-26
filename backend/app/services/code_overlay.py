"""On-demand source overlay for a run node — joins M1 run nodes to M2 git blobs.

No new tables: everything is derived from run_nodes / run_node_results / runs.scm_revision
and the project's bare clone. Run-visibility is enforced by the caller (VisibleRun).
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.path_schemas import NodeSourceOut, PathEdgeOut, PathNodeOut, ResolvedValueOut  # noqa: F401 (ResolvedValueOut exported for future tasks)
from app.core.config import settings
from app.logparser import parse_task_file
from app.models import Project, Run, RunNode, RunNodeResult
from app.projects.git import GitError, read_blob, revision_exists
from app.projects.storage import project_repo_path


def _jsonable(v):
    return v if isinstance(v, (str, int, float, bool, list, dict)) or v is None else str(v)


def resolved_values(node: RunNode, results: list[RunNodeResult]) -> list[ResolvedValueOut]:
    """What `{{ }}` resolved to for THIS run — only values Ansible actually recorded.
    Priority for module args: a result's res.invocation.module_args (fully rendered, per host),
    else the node's representative task_args (raw template → marked not-recorded)."""
    out: list[ResolvedValueOut] = []
    rep = next((r for r in results if isinstance(r.result, dict)), None)
    margs = None
    if rep is not None:
        inv = rep.result.get("invocation")
        if isinstance(inv, dict) and isinstance(inv.get("module_args"), dict):
            margs = inv["module_args"]
    if margs is not None:
        for k, v in margs.items():
            out.append(ResolvedValueOut(key=k, expr=None, value=_jsonable(v),
                                        source="module_args", recorded=True, host=rep.host))
    elif node.args:
        args = node.args.get("_raw") if set(node.args) == {"_raw"} else node.args
        if isinstance(args, dict):
            for k, v in args.items():
                unrendered = isinstance(v, str) and "{{" in v
                out.append(ResolvedValueOut(
                    key=k, expr=v if unrendered else None,
                    value=None if unrendered else _jsonable(v),
                    source="task_args", recorded=not unrendered, host=None))
    item_res = next((r for r in results if r.item_value is not None), None)
    if item_res is not None:
        out.append(ResolvedValueOut(key="item", expr="{{ item }}", value=_jsonable(item_res.item_value),
                                    source="item", recorded=True, host=item_res.host))
    when = node.when_expr or next((r.false_condition for r in results if r.false_condition), None)
    if when:
        out.append(ResolvedValueOut(key="when", expr=when, value=None, source="when",
                                    recorded=True, host=None))
    return out


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
    results = (await db.execute(
        select(RunNodeResult).where(RunNodeResult.run_id == run.id,
                                    RunNodeResult.node_id == node.node_id)
    )).scalars().all()
    resolved = resolved_values(node, results)
    hosts = sorted({r.host for r in results})
    base = dict(project_id=None, path=None, ref=run.scm_revision, content=None,
                focus_line=None, executed_lines=[], never_run_lines=[],
                resolved=resolved, hosts=hosts)
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

    executed = await _executed_lines_for_file(db, run.id, file)
    statics = parse_task_file(blob.text)
    executed_set = set(executed)
    never_run = sorted({st.line for st in statics if not st.is_block and st.line not in executed_set})
    base.update(content=blob.text, executed_lines=executed, never_run_lines=never_run)
    return NodeSourceOut(**base)


async def never_run_branches(db: AsyncSession, run: Run,
                             view_nodes: list[RunNode]) -> tuple[list[PathNodeOut], list[PathEdgeOut]]:
    """Ghost nodes for tasks present in the touched source but never executed, each hung off an
    executed view node via a `never_run` branch edge. Empty when the project isn't cloned / the
    revision isn't fetched (the flow toggle then simply shows nothing extra)."""
    proj = await resolve_project_for_run(db, run)
    if proj is None or proj.status != "cloned" or not run.scm_revision:
        return [], []
    repo = project_repo_path(proj.id)
    if not repo.exists() or not await revision_exists(repo, run.scm_revision):
        return [], []

    # Executed lines per file across the WHOLE run (so a sibling executed outside this view counts).
    all_paths = (await db.execute(
        select(RunNode.task_path).where(RunNode.run_id == run.id, RunNode.task_path.isnot(None))
    )).scalars().all()
    executed_by_file: dict[str, set[int]] = {}
    for tp in all_paths:
        sp = split_task_path(tp)
        if sp:
            executed_by_file.setdefault(sp[0], set()).add(sp[1])

    ghosts: list[PathNodeOut] = []
    edges: list[PathEdgeOut] = []
    seen: set[tuple[str, int]] = set()
    parsed: dict[str, list] = {}
    cap = settings.project_blob_max_bytes
    for vn in view_nodes:
        sp = split_task_path(vn.task_path)
        if sp is None:
            continue
        file = sp[0]
        if file not in parsed:
            try:
                blob = await read_blob(repo, run.scm_revision, file, cap)
            except GitError:
                parsed[file] = []  # unreadable/binary/too-large blob → no ghosts for this file
                continue
            parsed[file] = parse_task_file(blob.text) if blob.text else []
        execed = executed_by_file.get(file, set())
        for st in parsed[file]:
            if st.is_block or st.line in execed:
                continue
            key = (file, st.line)
            if key in seen:
                continue
            seen.add(key)
            gid = f"nr:{file}:{st.line}"
            ghosts.append(PathNodeOut(
                id=gid, type="task", label=st.name or st.action or "task",
                sub=st.action, status="skipped", action=st.action,
                condition=st.when, is_conditional=bool(st.when),
                never_run=True, task_path=f"{file}:{st.line}",
            ))
            edges.append(PathEdgeOut(from_=vn.node_id, to=gid, branch="never_run"))
    return ghosts, edges
