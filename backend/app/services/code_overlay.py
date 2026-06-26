"""On-demand source overlay for a run node — joins M1 run nodes to M2 git blobs.

No new tables: everything is derived from run_nodes / run_node_results / runs.scm_revision
and the project's bare clone. Run-visibility is enforced by the caller (VisibleRun).
"""
from __future__ import annotations

from bisect import bisect_right

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


def _build_file_ghosts(file: str, statics: list, execed: set[int],
                       anchors: list[tuple[int, str]]) -> tuple[list[PathNodeOut], list[PathEdgeOut]]:
    """Nested never-run ghost sub-tree for one file. Never-run leaf tasks and wholly-never-run
    blocks become ghost nodes; a ghost block's children nest under it, sibling ghosts chain in
    source order, and each top-level chain branches off its nearest preceding executed view node
    (`anchors` = sorted [(line, node_id)] of the file's executed view nodes). Pure (no DB/HTTP)."""
    children_of: dict[int | None, list] = {}
    for st in statics:  # statics arrive sorted by line, so child lists stay in source order
        children_of.setdefault(st.parent_line, []).append(st)

    memo: dict[int, bool] = {}

    def block_ran(block_line: int) -> bool:
        """A block 'ran' if any descendant leaf task executed — such a block is NOT a ghost."""
        if block_line in memo:
            return memo[block_line]
        memo[block_line] = False  # cycle guard
        ran = False
        for ch in children_of.get(block_line, []):
            if (block_ran(ch.line) if ch.is_block else ch.line in execed):
                ran = True
                break
        memo[block_line] = ran
        return ran

    def is_ghost(st) -> bool:
        # a leaf task is a ghost if it never executed; a block is a ghost if it wholly never ran
        return (not block_ran(st.line)) if st.is_block else (st.line not in execed)

    ghost_lines = {st.line for st in statics if is_ghost(st)}
    if not ghost_lines or not anchors:
        return [], []

    def gid(line: int) -> str:
        return f"nr:{file}:{line}"

    nodes: list[PathNodeOut] = []
    for st in statics:
        if st.line not in ghost_lines:
            continue
        if st.is_block:
            nodes.append(PathNodeOut(id=gid(st.line), type="block", label=st.name or "block",
                                     sub="block", status="skipped", condition=st.when,
                                     is_conditional=bool(st.when), never_run=True,
                                     task_path=f"{file}:{st.line}"))
        else:
            nodes.append(PathNodeOut(id=gid(st.line), type="task",
                                     label=st.name or st.action or "task", sub=st.action,
                                     status="skipped", action=st.action, condition=st.when,
                                     is_conditional=bool(st.when), never_run=True,
                                     task_path=f"{file}:{st.line}"))

    edges: list[PathEdgeOut] = []
    # nest: each ghost block's ghost children chain under it
    for st in statics:
        if st.line in ghost_lines and st.is_block:
            prev: int | None = None
            for ch in children_of.get(st.line, []):
                if ch.line not in ghost_lines:
                    continue
                frm = gid(st.line) if prev is None else gid(prev)
                edges.append(PathEdgeOut(from_=frm, to=gid(ch.line), branch="never_run"))
                prev = ch.line

    # top-level ghosts (not nested under a ghost block) branch off the nearest preceding executed
    # view node; consecutive top-level ghosts sharing an anchor chain together (one dashed path).
    anchor_lines = [ln for ln, _ in anchors]
    prev_node: str | None = None
    prev_anchor: str | None = None
    for st in statics:
        if st.line not in ghost_lines or st.parent_line in ghost_lines:
            continue
        i = bisect_right(anchor_lines, st.line)
        anchor_id = anchors[i - 1][1] if i > 0 else anchors[0][1]
        frm = prev_node if (prev_node is not None and anchor_id == prev_anchor) else anchor_id
        edges.append(PathEdgeOut(from_=frm, to=gid(st.line), branch="never_run"))
        prev_node, prev_anchor = gid(st.line), anchor_id

    return nodes, edges


async def never_run_branches(db: AsyncSession, run: Run,
                             view_nodes: list[RunNode]) -> tuple[list[PathNodeOut], list[PathEdgeOut]]:
    """Ghost nodes for tasks present in the touched source but never executed. Each ghost hangs off
    the executed view node that is its nearest PRECEDING sibling by source line, so never-run
    branches distribute across the flow at the point they would have run (a tree) rather than all
    stemming from the first node. Empty when the project isn't cloned / the revision isn't fetched."""
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

    # Anchor candidates per file: the executed view nodes that carry a source line, sorted by line.
    # A never-run task attaches to the nearest preceding one (bisect) so ghosts branch off the flow
    # where they would have run, rather than all stemming from the first node.
    anchors_by_file: dict[str, list[tuple[int, str]]] = {}
    for vn in view_nodes:
        sp = split_task_path(vn.task_path)
        if sp:
            anchors_by_file.setdefault(sp[0], []).append((sp[1], vn.node_id))
    for f in anchors_by_file:
        anchors_by_file[f].sort()

    ghosts: list[PathNodeOut] = []
    edges: list[PathEdgeOut] = []
    cap = settings.project_blob_max_bytes
    for file, anchors in anchors_by_file.items():
        try:
            blob = await read_blob(repo, run.scm_revision, file, cap)
        except GitError:
            continue  # unreadable/binary/too-large blob → no ghosts for this file
        if not blob.text:
            continue
        execed = executed_by_file.get(file, set())
        fnodes, fedges = _build_file_ghosts(file, parse_task_file(blob.text), execed, anchors)
        ghosts += fnodes
        edges += fedges
    return ghosts, edges
