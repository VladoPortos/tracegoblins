from __future__ import annotations

from app.api.path_schemas import PathEdgeOut, PathNodeOut

_RANK = {"skipped": 0, "ok": 1, "changed": 2, "failed": 3, "unreachable": 4}


def _disjoint(sets: list[set[str]]) -> bool:
    seen: set[str] = set()
    for s in sets:
        if not s or (s & seen):
            return False
        seen |= s
    return True


def synthesize_forks(
    nodes: list[PathNodeOut], taken_hosts: dict[str, set[str]]
) -> tuple[list[PathNodeOut], list[PathEdgeOut]]:
    """Group maximal runs of >=2 consecutive conditional nodes with pairwise-disjoint, non-empty
    taken-host sets into a synthetic `when` fork. Pure; no DB. Returns (nodes, edges)."""
    # 1. partition the ordered nodes into "units": single node, or a fork group (list of branches)
    units: list[dict] = []
    i = 0
    while i < len(nodes):
        if nodes[i].is_conditional:
            j = i
            while j < len(nodes) and nodes[j].is_conditional:
                j += 1
            group = nodes[i:j]
            if len(group) >= 2 and _disjoint([taken_hosts.get(g.id, set()) for g in group]):
                units.append({"kind": "fork", "branches": group})
                i = j
                continue
        units.append({"kind": "single", "node": nodes[i]})
        i += 1

    # 2. emit nodes (insert a `when` node per fork; tag each branch) + within-fork edges
    out_nodes: list[PathNodeOut] = []
    edges: list[PathEdgeOut] = []
    for u in units:
        if u["kind"] == "single":
            out_nodes.append(u["node"])
            continue
        branches = u["branches"]
        worst = max((b.status for b in branches), key=lambda s: _RANK.get(s, 0))
        when = PathNodeOut(
            id=f"when:{branches[0].id}", type="when", label="decision", sub="decision",
            status=worst, is_conditional=True, condition=branches[0].condition,
            has_failures=any(b.has_failures for b in branches),
        )
        u["when_id"] = when.id
        out_nodes.append(when)
        for b in branches:
            b.branch = b.id
            out_nodes.append(b)
            edges.append(PathEdgeOut(from_=when.id, to=b.id, branch=b.id))

    # 3. edges between consecutive units (a unit's exit points fan into the next unit's entry)
    def entry(u: dict) -> str:
        return u["when_id"] if u["kind"] == "fork" else u["node"].id

    def exits(u: dict) -> list[tuple[str, str | None]]:
        if u["kind"] == "fork":
            return [(b.id, b.id) for b in u["branches"]]
        return [(u["node"].id, None)]

    for prev, nxt in zip(units, units[1:]):
        nxt_entry = entry(nxt)
        for exit_id, br in exits(prev):
            edges.append(PathEdgeOut(from_=exit_id, to=nxt_entry, branch=br))
    return out_nodes, edges
