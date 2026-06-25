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


def build_tree(events: list[dict]) -> ParsedTree:
    """Reconstruct the structural execution tree from AWX job_events. Pure. Built up across
    Tasks 2–4; this stub returns an empty tree."""
    return ParsedTree()
