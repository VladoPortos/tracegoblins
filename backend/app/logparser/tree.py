from __future__ import annotations

from dataclasses import dataclass, field


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


def _norm(s: str) -> str:
    s = s or ""
    return s[3:] if s.startswith("v2_") else s


def _strip_project_path(p: str | None) -> str | None:
    if not p:
        return None
    return p[len(_PROJECT_PREFIX):] if p.startswith(_PROJECT_PREFIX) else p


def build_tree(events: list[dict]) -> ParsedTree:
    """Reconstruct the structural execution tree from AWX job_events. Pure. Built up across
    Tasks 2–4; single-pass walk in counter order."""
    tree = ParsedTree()
    root = TreeNode(node_id="root", parent_id=None, counter=0, depth=-1,
                    node_type="playbook", name="playbook")
    tree.nodes.append(root)

    cur_play: TreeNode | None = None
    # index nodes by their ansible uuid so later events (results, includes) can find them
    by_uuid: dict[str, TreeNode] = {}

    for ev in events:
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
            continue

        if et in ("playbook_on_task_start", "playbook_on_handler_task_start"):
            if cur_play is None:  # tasks before any play_start — synthesize a play
                cur_play = TreeNode(node_id=f"play-{counter}", parent_id=root.node_id,
                                    counter=counter, depth=0, node_type="play", name="play")
                tree.nodes.append(cur_play)
            task_uuid = ed.get("task_uuid") or ed.get("uuid") or f"task-{counter}"
            node = TreeNode(
                node_id=task_uuid, parent_id=cur_play.node_id, counter=counter, depth=1,
                node_type="task", name=ed.get("task") or ed.get("name") or "task",
                action=ed.get("task_action") or ed.get("resolved_action"),
                task_path=_strip_project_path(ed.get("task_path")),
                ansible_uuid=task_uuid,
                is_conditional=bool(ed.get("is_conditional")),
            )
            tree.nodes.append(node)
            by_uuid[task_uuid] = node
            continue

    # stash for later tasks
    tree.__dict__["_by_uuid"] = by_uuid  # internal handoff to Task 3/4 passes; not serialized
    return tree
