"""On-demand source overlay for a run node — joins M1 run nodes to M2 git blobs.

No new tables: everything is derived from run_nodes / run_node_results / runs.scm_revision
and the project's bare clone. Run-visibility is enforced by the caller (VisibleRun).
"""
from __future__ import annotations

import posixpath
from bisect import bisect_right

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.path_schemas import NodeSourceOut, PathEdgeOut, PathNodeOut, ResolvedValueOut  # noqa: F401 (ResolvedValueOut exported for future tasks)
from app.core.config import settings
from app.logparser import parse_task_file
from app.logparser.playbook_static import module_arg_exprs
from app.models import Project, Run, RunNode, RunNodeResult
from app.projects.git import GitError, read_blob, revision_exists
from app.projects.storage import project_repo_path


# Static include/import directives are pre-expanded by Ansible — the directive line emits no runner
# event, so it must never be classified never-run/ghost (OV3). Both short and FQCN forms.
_STATIC_IMPORTS = {
    "import_tasks", "import_role", "import_playbook",
    "ansible.builtin.import_tasks", "ansible.builtin.import_role", "ansible.builtin.import_playbook",
}


def _is_static_import(st) -> bool:
    return not st.is_block and st.action in _STATIC_IMPORTS


def _jsonable(v):
    return v if isinstance(v, (str, int, float, bool, list, dict)) or v is None else str(v)


def _action_is(node: RunNode, name: str) -> bool:
    """True when the node's module is `name`, matching both short and FQCN forms (set_fact / debug)."""
    a = node.action or ""
    return a == name or a.endswith("." + name)


def _module_args(result) -> dict | None:
    """`res.invocation.module_args` when it's a dict, else None — guards against a malformed
    `invocation` (string/list/None) raising AttributeError on the chained .get() (PATH3)."""
    if not isinstance(result, dict):
        return None
    inv = result.get("invocation")
    ma = inv.get("module_args") if isinstance(inv, dict) else None
    return ma if isinstance(ma, dict) else None


def resolved_values(node: RunNode, results: list[RunNodeResult]) -> list[ResolvedValueOut]:
    """What `{{ }}` resolved to for THIS run — only values Ansible actually recorded. Reads the
    several places AWX stashes rendered values: module tasks → res.invocation.module_args (rendered
    per host); set_fact → res.ansible_facts; debug → res.msg/res.var; loops → item; conditional →
    when. task_args is a last-resort fallback (AWX usually emits it empty)."""
    out: list[ResolvedValueOut] = []

    # 1. module_args — the rendered args of a real module call (the representative host MUST be one
    #    that actually carries module_args, not merely the first dict result) (VV-D).
    rep = next((r for r in results if _module_args(r.result) is not None), None)
    if rep is not None:
        for k, v in _module_args(rep.result).items():
            out.append(ResolvedValueOut(key=k, expr=None, value=_jsonable(v),
                                        source="module_args", recorded=True, host=rep.host))

    # 2. set_fact — the variables it assigned, recorded under res.ansible_facts (VV-SETFACT).
    if _action_is(node, "set_fact"):
        fr = next((r for r in results if isinstance(r.result, dict)
                   and isinstance(r.result.get("ansible_facts"), dict)), None)
        if fr is not None:
            for k, v in fr.result["ansible_facts"].items():
                out.append(ResolvedValueOut(key=k, expr=None, value=_jsonable(v),
                                            source="set_fact", recorded=True, host=fr.host))

    # 3. debug — what it printed (res.msg / res.var) (VV-SETFACT).
    if _action_is(node, "debug"):
        dr = next((r for r in results if isinstance(r.result, dict)
                   and (r.result.get("msg") is not None or r.result.get("var") is not None)), None)
        if dr is not None:
            if dr.result.get("msg") is not None:
                out.append(ResolvedValueOut(key="msg", expr=None, value=_jsonable(dr.result["msg"]),
                                            source="debug", recorded=True, host=dr.host))
            if dr.result.get("var") is not None:
                out.append(ResolvedValueOut(key="var", expr=None, value=_jsonable(dr.result["var"]),
                                            source="debug", recorded=True, host=dr.host))

    # 4. task_args — last-resort fallback (AWX usually emits task_args empty, so this rarely fires;
    #    a still-templated value is shown as its raw expr, marked not-recorded).
    if not out and node.args:
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


async def when_by_line(db: AsyncSession, run: Run, files: set[str]) -> dict[tuple[str, int], str]:
    """`(file, line) -> when` text from the static parse at the run's revision, for the given files.
    Empty when the project isn't cloned / the revision isn't fetched (the fork still renders, just
    without condition text). Pure-ish: only reads git blobs + the pure parser."""
    if not files:
        return {}
    proj = await resolve_project_for_run(db, run)
    if proj is None or proj.status != "cloned" or not run.scm_revision:
        return {}
    repo = project_repo_path(proj.id)
    if not repo.exists() or not await revision_exists(repo, run.scm_revision):
        return {}
    out: dict[tuple[str, int], str] = {}
    cap = settings.project_blob_max_bytes
    for f in files:
        try:
            blob = await read_blob(repo, run.scm_revision, f, cap)
        except GitError:
            continue
        if not blob.text:
            continue
        for st in parse_task_file(blob.text):
            if st.when:
                out[(f, st.line)] = st.when
    return out


async def _executed_and_skipped_lines_for_file(
    db: AsyncSession, run_id, file: str
) -> tuple[list[int], list[int]]:
    """(executed_lines, skipped_lines) for one file. A line is SKIPPED only when every node at it
    skipped (reached-and-skipped, OV4); any non-skipped node makes the line executed."""
    rows = (await db.execute(
        select(RunNode.task_path, RunNode.status).where(
            RunNode.run_id == run_id, RunNode.task_path.isnot(None))
    )).all()
    by_line: dict[int, set[str]] = {}
    for tp, status in rows:
        if (sp := split_task_path(tp)) and sp[0] == file:
            by_line.setdefault(sp[1], set()).add(status)
    executed = sorted(ln for ln, sts in by_line.items() if sts != {"skipped"})
    skipped = sorted(ln for ln, sts in by_line.items() if sts == {"skipped"})
    return executed, skipped


async def _build_source(db: AsyncSession, run: Run, *, file: str, focus_line: int | None,
                        resolved: list[ResolvedValueOut], hosts: list[str]) -> NodeSourceOut:
    """Shared overlay payload for one file at the run's revision — used by both real nodes and
    never-run ghosts. Degrades (200 + `unavailable`) when the project isn't linked/cloned/fetched."""
    base = dict(project_id=None, path=file, ref=run.scm_revision, content=None,
                focus_line=focus_line, executed_lines=[], skipped_lines=[], never_run_lines=[],
                resolved=resolved, hosts=hosts, revision_mismatch=False)
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

    executed, skipped = await _executed_and_skipped_lines_for_file(db, run.id, file)
    statics = parse_task_file(blob.text)
    touched = set(executed) | set(skipped)  # never-run = present in source but Ansible never reached it
    never_run = sorted({st.line for st in statics
                        if not st.is_block and st.line not in touched and not _is_static_import(st)})
    # OV8: a recorded line past EOF means the clone/revision doesn't match what actually ran — flag it
    # rather than silently dropping the (un-renderable) decoration.
    doc_lines = blob.text.count("\n") + 1
    recorded = set(executed) | set(skipped) | ({focus_line} if focus_line else set())
    # VV-C: pair each resolved value with the raw `{{ }}` expr from the focused task's source, so the
    # user sees which template a value came from (e.g. cdb_host  {{ cdb_fqdn }} → "cdb...").
    if focus_line and resolved:
        exprs = module_arg_exprs(blob.text, focus_line)
        for r in resolved:
            if r.expr is None and (e := exprs.get(r.key)) and "{{" in e:
                r.expr = e
    base.update(content=blob.text, executed_lines=executed, skipped_lines=skipped,
                never_run_lines=never_run, revision_mismatch=any(ln > doc_lines for ln in recorded))
    return NodeSourceOut(**base)


async def build_node_source(db: AsyncSession, run: Run, node: RunNode) -> NodeSourceOut:
    results = (await db.execute(
        select(RunNodeResult).where(RunNodeResult.run_id == run.id,
                                    RunNodeResult.node_id == node.node_id)
    )).scalars().all()
    resolved = resolved_values(node, results)
    hosts = sorted({r.host for r in results})
    sp = split_task_path(node.task_path)
    if sp is None:
        return NodeSourceOut(project_id=None, path=None, ref=run.scm_revision, content=None,
                             focus_line=None, executed_lines=[], skipped_lines=[], never_run_lines=[],
                             resolved=resolved, hosts=hosts, unavailable="no_path")
    return await _build_source(db, run, file=sp[0], focus_line=sp[1], resolved=resolved, hosts=hosts)


async def build_ghost_source(db: AsyncSession, run: Run, file: str, line: int) -> NodeSourceOut:
    """Overlay payload for a never-run ghost (OV5). The ghost has no results, so resolved/hosts are
    empty; its line is greyed via never_run_lines."""
    return await _build_source(db, run, file=file, focus_line=line, resolved=[], hosts=[])


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
        # a leaf task is a ghost if it never executed; a block is a ghost if it wholly never ran.
        # static imports are pre-expanded (no runner event) → never a ghost (OV3).
        if _is_static_import(st):
            return False
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
        # NR1: never-reached tasks are "never_run", distinct from evaluated-and-"skipped". condition/
        # is_conditional are set ONLY when the static task actually carries a `when:`.
        if st.is_block:
            nodes.append(PathNodeOut(id=gid(st.line), type="block", label=st.name or "block",
                                     sub="block", status="never_run", condition=st.when,
                                     is_conditional=bool(st.when), never_run=True,
                                     task_path=f"{file}:{st.line}"))
        else:
            sub = st.action
            if st.section in ("rescue", "always"):  # surface error-handler sections on the ghost
                sub = f"{st.section}: {st.action}" if st.action else st.section
            nodes.append(PathNodeOut(id=gid(st.line), type="task",
                                     label=st.name or st.action or "task", sub=sub,
                                     status="never_run", action=st.action, condition=st.when,
                                     is_conditional=bool(st.when), never_run=True,
                                     task_path=f"{file}:{st.line}"))

    edges: list[PathEdgeOut] = []
    # nest: each ghost block's ghost children chain under it, grouped by section so that block /
    # rescue / always render as separate sub-branches off the block (not one flat chain).
    for st in statics:
        if st.line in ghost_lines and st.is_block:
            kids = [c for c in children_of.get(st.line, []) if c.line in ghost_lines]
            for sect in ("block", "rescue", "always"):
                prev: int | None = None
                for ch in kids:
                    if (ch.section or "block") != sect:
                        continue
                    frm = gid(st.line) if prev is None else gid(prev)
                    edges.append(PathEdgeOut(from_=frm, to=gid(ch.line), branch="never_run"))
                    prev = ch.line

    # top-level ghosts (not nested under a ghost block).
    top = [st for st in statics if st.line in ghost_lines and st.parent_line not in ghost_lines]
    first_line = anchors[0][0]

    # prefix ghosts (before the first executed anchor) chain in source order and LEAD INTO the
    # first executed node — rather than incorrectly branching off a task that comes after them.
    prefix_prev: int | None = None
    for st in top:
        if st.line >= first_line:
            continue
        if prefix_prev is not None:
            edges.append(PathEdgeOut(from_=gid(prefix_prev), to=gid(st.line), branch="never_run"))
        prefix_prev = st.line
    if prefix_prev is not None:
        edges.append(PathEdgeOut(from_=gid(prefix_prev), to=anchors[0][1], branch="never_run"))

    # remaining top-level ghosts branch off their nearest preceding executed view node; consecutive
    # same-anchor ghosts chain together into one dashed road-not-taken.
    anchor_lines = [ln for ln, _ in anchors]
    prev_node: str | None = None
    prev_anchor: str | None = None
    for st in top:
        if st.line < first_line:
            continue
        i = bisect_right(anchor_lines, st.line)
        anchor_id = anchors[i - 1][1]  # st.line >= first_line ⇒ i >= 1, so a preceding anchor exists
        frm = prev_node if (prev_node is not None and anchor_id == prev_anchor) else anchor_id
        edges.append(PathEdgeOut(from_=frm, to=gid(st.line), branch="never_run"))
        prev_node, prev_anchor = gid(st.line), anchor_id

    return nodes, edges


def _resolve_include(including_file: str, st) -> str | None:
    """Repo-relative path of an include/import target (NR2). `include_role`/`import_role` → the role's
    tasks/main.yml; `include_tasks`/`import_tasks` → the file relative to the including file's dir.
    None for a templated (`{{ }}`) target, which can't be resolved statically."""
    target = st.target
    if not target or "{{" in target:
        return None
    act = st.action or ""
    if act.endswith("include_role") or act.endswith("import_role"):
        return f"roles/{target}/tasks/main.yml"
    return posixpath.normpath(posixpath.join(posixpath.dirname(including_file), target))


def _partition_by_play(statics: list, anchors: list[tuple[int, str]]) -> list[tuple[list, list]]:
    """Split a file's (statics, anchors) into per-play groups so ghosts never anchor across a play
    boundary within the same file (NR4). Task-only files (no play header) stay one group."""
    play_lines = sorted({st.play_line for st in statics if st.play_line is not None})
    if not play_lines:
        return [(statics, anchors)]

    def play_of(line: int) -> int | None:
        p: int | None = None
        for pl in play_lines:
            if pl <= line:
                p = pl
            else:
                break
        return p

    groups = [([st for st in statics if st.play_line == pl],
               [a for a in anchors if play_of(a[0]) == pl]) for pl in play_lines]
    pre = [st for st in statics if st.play_line is None]  # content before the first play (rare)
    if pre:
        groups.append((pre, [a for a in anchors if play_of(a[0]) is None]))
    return groups


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
    statics_by_file: dict[str, list] = {}
    for file, anchors in anchors_by_file.items():
        try:
            blob = await read_blob(repo, run.scm_revision, file, cap)
        except GitError:
            continue  # unreadable/binary/too-large blob → no ghosts for this file
        if not blob.text:
            continue
        execed = executed_by_file.get(file, set())
        statics = parse_task_file(blob.text)
        statics_by_file[file] = statics
        for g_statics, g_anchors in _partition_by_play(statics, anchors):
            fnodes, fedges = _build_file_ghosts(file, g_statics, execed, g_anchors)
            ghosts += fnodes
            edges += fedges

    # NR2: an include/import whose TARGET file never ran (e.g. a skipped conditional include) →
    # surface the target's tasks as ghosts hanging off the include node, so a wholly-never-run
    # include is visible road-not-taken (not silently absent).
    emitted: set[str] = set()
    for file, anchors in anchors_by_file.items():
        anchor_at = {ln: nid for ln, nid in anchors}
        for st in statics_by_file.get(file, []):
            anchor_id = anchor_at.get(st.line)          # the include must itself be a view node
            if anchor_id is None or not st.target:
                continue
            target = _resolve_include(file, st)
            if not target or target in emitted or executed_by_file.get(target):
                continue                                 # templated, already done, or it actually ran
            try:
                tblob = await read_blob(repo, run.scm_revision, target, cap)
            except GitError:
                continue
            if not tblob.text:
                continue
            # anchor everything off the include node via a synthetic pre-anchor at line 0
            tnodes, tedges = _build_file_ghosts(target, parse_task_file(tblob.text), set(),
                                                [(0, anchor_id)])
            ghosts += tnodes
            edges += tedges
            emitted.add(target)
    return ghosts, edges
