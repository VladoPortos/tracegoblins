"""Pure container-status rollup for the run path tree.

AWX results are keyed to leaf task nodes only; play / role / include / block containers
carry no direct result, so without a rollup they keep their default ``status="ok"`` even
when a descendant failed (PT1). This computes each container's status as the worst
(:data:`_RANK`) leaf status in its subtree. Leaf nodes keep their own status.

Applied BOTH at ingestion (build_tree, correct-at-source) and at read time (get_run_tree,
backfills already-ingested runs with no re-sync) via the same pure function.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Iterable

from app.core import statuses

CONTAINER_TYPES = {"playbook", "play", "role", "include", "block"}


def rolled_up_status(rows: Iterable[tuple[str, str | None, str, str]]) -> dict[str, str]:
    """Map node_id -> effective status.

    ``rows`` are ``(node_id, parent_id, node_type, own_status)``. A container
    (``node_type in CONTAINER_TYPES``) with children gets the worst status across its
    whole subtree; a container with no children, and every leaf, keeps ``own_status``.
    Pure and cycle-guarded.
    """
    children: dict[str | None, list[str]] = defaultdict(list)
    ntype: dict[str, str] = {}
    own: dict[str, str] = {}
    for nid, pid, nt, st in rows:
        children[pid].append(nid)
        ntype[nid] = nt
        own[nid] = st

    memo: dict[str, str] = {}

    def eff(nid: str) -> str:
        if nid in memo:
            return memo[nid]
        memo[nid] = own.get(nid, "ok")  # cycle guard
        kids = children.get(nid, [])
        if ntype.get(nid) in CONTAINER_TYPES and kids:
            best = "skipped"
            for c in kids:
                cs = eff(c)
                if statuses.rank(cs) > statuses.rank(best):
                    best = cs
            memo[nid] = best
        else:
            memo[nid] = own.get(nid, "ok")
        return memo[nid]

    for nid in own:
        eff(nid)
    return memo
