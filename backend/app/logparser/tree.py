from __future__ import annotations

import json
from collections import Counter, defaultdict
from dataclasses import dataclass, field

from app.core import statuses
from app.logparser.job_events import _host as resolve_host
from app.services.status_rollup import rolled_up_status


@dataclass
class TreeNode:
    node_id: str                      # stable id (ansible task_uuid/play_uuid, or synthetic)
    parent_id: str | None             # node_id of the structural parent; None = run root child
    counter: int                      # AWX event counter — canonical ordering among siblings
    depth: int                        # 0 = play band; precomputed for layout/lazy-load
    node_type: str                    # playbook | play | role | include | task | loop
    name: str
    action: str | None = None         # task_action / resolved_action
    task_path: str | None = None      # file:line, repo-root relative (no /runner/project/)
    ansible_uuid: str | None = None   # task_uuid / play_uuid — M3 source-map link
    is_conditional: bool = False
    is_handler: bool = False          # node came from playbook_on_handler_task_start (notified + fired)
    when_expr: str | None = None      # res.false_condition when known
    loop_var: str | None = None       # event_loop
    status: str = "ok"                # aggregate worst across results
    changed: bool = False             # any result changed
    host_count: int = 0
    item_count: int = 0
    child_count: int = 0              # container child count (filled by build_tree)
    started_at: str | None = None     # ISO string; mapped to DateTime at persist time
    duration_s: float | None = None
    args: dict | None = None          # representative task_args (capped, no_log-aware)


@dataclass
class TreeResult:
    node_id: str
    host: str
    item_index: int | None = None
    item_value: object | None = None
    status: str = "ok"
    changed: bool = False
    result: dict | None = None        # res payload (capped at persist time)
    skip_reason: str | None = None
    false_condition: str | None = None
    started_at: str | None = None
    ended_at: str | None = None
    duration_s: float | None = None


@dataclass
class ParsedTree:
    nodes: list[TreeNode] = field(default_factory=list)
    results: list[TreeResult] = field(default_factory=list)


_PROJECT_PREFIX = "/runner/project/"

_TERMINAL: dict[str, str] = {
    "runner_on_ok": "ok",
    "runner_on_failed": "failed",
    "runner_on_unreachable": "unreachable",
    "runner_on_skipped": "skipped",
}
_ITEM: dict[str, str] = {
    "runner_item_on_ok": "ok",
    "runner_item_on_failed": "failed",
    "runner_item_on_skipped": "skipped",
}
_MAX_BLOB_CHARS = 64_000


def _cap_result(res: dict | None) -> dict | None:
    if not res:
        return None
    s = json.dumps(res, ensure_ascii=False)
    if len(s) <= _MAX_BLOB_CHARS:
        return res
    return {"_truncated": True, "_preview": s[:_MAX_BLOB_CHARS]}


def _norm(s: str) -> str:
    s = s or ""
    return s[3:] if s.startswith("v2_") else s


def _strip_project_path(p: str | None) -> str | None:
    if not p:
        return None
    return p[len(_PROJECT_PREFIX):] if p.startswith(_PROJECT_PREFIX) else p


def _task_file(task_path: str | None) -> str | None:
    """Return the file portion of a stripped task_path (drop :lineno suffix)."""
    if not task_path:
        return None
    return task_path.rsplit(":", 1)[0]


def build_tree(events: list[dict]) -> ParsedTree:
    """Reconstruct the structural execution tree from AWX job_events. Pure. Built up across
    Tasks 2–4; single-pass walk in counter order.

    Container reconstruction (Task 3)
    ----------------------------------
    AWX flattens all tasks under their play — every task's parent_uuid is the play.  We
    reconstruct logical nesting from two signals:

    1. ``playbook_on_include`` events carry ``included_file``.  We maintain an *active include
       stack* (one entry per open include).  When a task starts, we scan the stack from the
       top; if its ``task_path`` file matches a stack entry we pop down to that entry and place
       the task under the corresponding include container.  If no entry matches, the task is
       top-level (parented directly to the play) and the stack is cleared.

    2. ``event_data.role`` — tasks carrying a role name that are not captured by an active
       include are placed under a ``role`` container within the play.

    Limitation: Ansible ``block:`` boundaries emit no events, so block containers cannot be
    reconstructed here (M3 will add them via a static overlay).  Nested includes-within-includes
    collapse to the innermost matching file container.
    """
    tree = ParsedTree()
    root = TreeNode(node_id="root", parent_id=None, counter=0, depth=-1,
                    node_type="playbook", name="playbook")
    tree.nodes.append(root)

    cur_play: TreeNode | None = None
    # index nodes by their ansible uuid so later events (results, includes) can find them
    by_uuid: dict[str, TreeNode] = {}
    # container cache: (play_id, kind, key) -> container TreeNode
    containers: dict[tuple, TreeNode] = {}
    # active include stack: list of (stripped_included_file, basename) in push order
    include_stack: list[tuple[str, str]] = []  # (stripped_path, basename)

    # Per-(node_id, host) running counter for loop item events — avoids the O(n²)
    # list scan and keeps each host's item indices independent (0..K-1 per host).
    _item_counter: dict[tuple[str, str], int] = {}

    for ev in sorted(events, key=lambda e: e.get("counter") or 0):
        et = _norm(ev.get("event", ""))
        ed = ev.get("event_data") or {}
        counter = ev.get("counter") or 0

        if et == "playbook_on_play_start":
            play_uuid = ed.get("play_uuid") or ed.get("uuid") or f"play-{counter}"
            cur_play = TreeNode(
                node_id=play_uuid, parent_id=root.node_id, counter=counter, depth=0,
                node_type="play", name=ed.get("play") or ed.get("name") or "play",
                ansible_uuid=play_uuid,
            )
            tree.nodes.append(cur_play)
            by_uuid[play_uuid] = cur_play
            # new play resets include state
            include_stack.clear()
            continue

        if et == "playbook_on_include":
            inc_file = _strip_project_path(ed.get("included_file") or "") or ""
            base = inc_file.rsplit("/", 1)[-1] or inc_file
            include_stack.append((inc_file, base))
            continue

        if et in ("playbook_on_task_start", "playbook_on_handler_task_start"):
            if cur_play is None:  # tasks before any play_start — synthesize a play
                cur_play = TreeNode(node_id=f"play-{counter}", parent_id=root.node_id,
                                    counter=counter, depth=0, node_type="play", name="play")
                tree.nodes.append(cur_play)

            task_uuid = ed.get("task_uuid") or ed.get("uuid") or f"task-{counter}"
            raw_path = _strip_project_path(ed.get("task_path"))
            task_file = _task_file(raw_path)

            # Resolve the active include container for this task.
            # Scan the stack from the top; pop entries that don't match this task's file.
            # If no entry matches, the task is top-level (stack is emptied).
            # Note: a task with no task_path falls through to play-level (does not consult
            # or clear the stack) — see the `if include_stack and task_file:` guard below.
            active_inc: tuple[str, str] | None = None
            if include_stack and task_file:
                for i in range(len(include_stack) - 1, -1, -1):
                    if include_stack[i][0] == task_file:
                        # Pop any deeper includes that are now closed
                        del include_stack[i + 1:]
                        active_inc = include_stack[i]
                        break
                else:
                    # Task file matches no open include → top-level, clear stack
                    include_stack.clear()

            # Determine structural parent (include container > role container > play)
            role = ed.get("role") or None
            if active_inc is not None:
                inc_path, inc_base = active_inc
                key = (cur_play.node_id, "include", inc_path)
                cont = containers.get(key)
                if cont is None:
                    cont = TreeNode(
                        node_id=f"inc:{cur_play.node_id}:{inc_path}",
                        parent_id=cur_play.node_id, counter=counter, depth=1,
                        node_type="include", name=inc_base,
                    )
                    tree.nodes.append(cont)
                    containers[key] = cont
                parent, task_depth = cont, 2
            elif role:
                key = (cur_play.node_id, "role", role)
                cont = containers.get(key)
                if cont is None:
                    cont = TreeNode(
                        node_id=f"role:{cur_play.node_id}:{role}",
                        parent_id=cur_play.node_id, counter=counter, depth=1,
                        node_type="role", name=role,
                    )
                    tree.nodes.append(cont)
                    containers[key] = cont
                parent, task_depth = cont, 2
            else:
                parent, task_depth = cur_play, 1

            node = TreeNode(
                node_id=task_uuid, parent_id=parent.node_id, counter=counter, depth=task_depth,
                node_type="task", name=ed.get("task") or ed.get("name") or "task",
                action=ed.get("task_action") or ed.get("resolved_action"),
                task_path=raw_path,
                ansible_uuid=task_uuid,
                is_conditional=bool(ed.get("is_conditional")),
                is_handler=(et == "playbook_on_handler_task_start"),
            )
            tree.nodes.append(node)
            by_uuid[task_uuid] = node
            continue

        if et in _TERMINAL:
            node = by_uuid.get(ed.get("task_uuid") or "")
            if node is None:
                continue
            res = ed.get("res") or {}
            st = _TERMINAL[et]
            if st == "ok" and res.get("changed"):
                st = "changed"
            host = resolve_host(ev) or "localhost"  # shared rule incl. integer-host fallback (PATH4)
            tree.results.append(TreeResult(
                node_id=node.node_id, host=host, status=st,
                changed=bool(res.get("changed")), result=_cap_result(res),
                skip_reason=res.get("skip_reason"), false_condition=res.get("false_condition"),
                started_at=ed.get("start"), ended_at=ed.get("end"),
                duration_s=ed.get("duration"),
            ))
            if node.started_at is None and ed.get("start"):
                node.started_at = ed.get("start")
            if st == "skipped" and res.get("false_condition") and not node.when_expr:
                node.when_expr = str(res.get("false_condition"))
            if ed.get("duration") is not None:
                node.duration_s = ed.get("duration")
            if node.args is None and ed.get("task_args"):
                ta = ed.get("task_args")
                node.args = {"_raw": ta} if isinstance(ta, str) else ta
            continue

        if et in _ITEM:
            node = by_uuid.get(ed.get("task_uuid") or "")
            if node is None:
                continue
            res = ed.get("res") or {}
            st = _ITEM[et]
            if st == "ok" and res.get("changed"):
                st = "changed"
            host = resolve_host(ev) or "localhost"  # shared rule incl. integer-host fallback (PATH4)
            _key = (node.node_id, host)
            idx = _item_counter.get(_key, 0)
            _item_counter[_key] = idx + 1
            tree.results.append(TreeResult(
                node_id=node.node_id, host=host, item_index=idx, item_value=res.get("item"),
                status=st, changed=bool(res.get("changed")), result=_cap_result(res),
                started_at=ed.get("start"), ended_at=ed.get("end"),
            ))
            if node.loop_var is None:
                node.loop_var = ed.get("event_loop")
            if st == "skipped" and res.get("false_condition") and not node.when_expr:
                node.when_expr = str(res.get("false_condition"))  # item-level when text (PT2)
            continue

    # Aggregate node-level status/counts and retype loop nodes.
    by_node: dict[str, list[TreeResult]] = defaultdict(list)
    for r in tree.results:
        by_node[r.node_id].append(r)
    for n in tree.nodes:
        rs = by_node.get(n.node_id, [])
        if not rs:
            continue
        items = [r for r in rs if r.item_index is not None]
        if items:
            n.node_type = "loop"
            host_counts = Counter(r.host for r in items)
            n.item_count = max(host_counts.values()) if host_counts else 0
        n.host_count = len({r.host for r in rs if r.status != "skipped"})
        worst = max(rs, key=lambda r: statuses.rank(r.status)).status
        n.status = worst
        n.changed = any(r.changed for r in rs)
        # AWX never sets event_data.is_conditional (always False on real data), so derive it:
        # a task that ran on some hosts and skipped on others is a real when-decision (PT2). A
        # single-host pure-skip stays non-conditional (renders as an inline skipped node, not a fork).
        taken = {r.host for r in rs if r.status != "skipped"}
        skipped = {r.host for r in rs if r.status == "skipped"}
        if taken and skipped:
            n.is_conditional = True

    # Compute child_count for every node after the walk.
    child_counts: dict[str, int] = {}
    for n in tree.nodes:
        if n.parent_id is not None:
            child_counts[n.parent_id] = child_counts.get(n.parent_id, 0) + 1
    for n in tree.nodes:
        n.child_count = child_counts.get(n.node_id, 0)

    # Roll container status up from descendants — plays/roles/includes/blocks carry no direct
    # result, so without this they stay "ok" even when a child failed (PT1).
    roll = rolled_up_status((n.node_id, n.parent_id, n.node_type, n.status) for n in tree.nodes)
    for n in tree.nodes:
        n.status = roll.get(n.node_id, n.status)

    # stash for later tasks
    tree.__dict__["_by_uuid"] = by_uuid  # internal handoff to Task 4; not serialized
    return tree
