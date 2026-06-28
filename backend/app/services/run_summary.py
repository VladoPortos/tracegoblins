"""Build a copy-pasteable Markdown summary of a real run — for filing a ticket or a KB entry.

Pure: no DB/HTTP. The endpoint loads the rows and hands them here. The summary walks the
*whole* run (not a single drilled-in view) so the path-to-failure is complete.
"""
from __future__ import annotations

import re

from app.core import statuses
from app.models import RunNode, RunNodeResult

_RECAP_COLS = ("ok", "changed", "failed", "unreachable", "skipped")
_ERR_KEYS = ("msg", "stderr", "module_stderr", "exception", "reason", "stdout")
_ERR_MAX = 200


def _err_excerpt(res: dict | None) -> str | None:
    """First non-empty, single-line error-ish field from a result payload, truncated."""
    if not res:
        return None
    for k in _ERR_KEYS:
        v = res.get(k)
        if isinstance(v, str) and v.strip():
            line = re.sub(r"\s+", " ", v).strip()
            return line[:_ERR_MAX] + ("…" if len(line) > _ERR_MAX else "")
    return None


def _node_path(node: RunNode, by_id: dict[str, RunNode]) -> str:
    """play › role/include › task breadcrumb, skipping the synthetic playbook root."""
    crumbs: list[str] = []
    cur: RunNode | None = node
    seen: set[str] = set()
    while cur is not None and cur.node_id not in seen:
        seen.add(cur.node_id)
        if cur.node_type != "playbook":
            crumbs.append(cur.name)
        cur = by_id.get(cur.parent_node_id) if cur.parent_node_id else None
    return " › ".join(reversed(crumbs))


def build_summary_md(
    run, nodes: list[RunNode], failed_results: list[RunNodeResult]
) -> str:
    """Render a Markdown run summary. `failed_results` are the RunNodeResult rows whose
    status is a failure, used for per-host error excerpts."""
    by_id = {n.node_id: n for n in nodes}
    name = run.template_name or "Run"
    lines: list[str] = [f"# Run summary: {name}", ""]

    meta: list[str] = [f"- **Status:** {run.status}"]
    if run.awx_job_id:
        meta.append(f"- **Job:** #{run.awx_job_id}")
    meta.append(f"- **Hosts:** {run.host_count}")
    if run.elapsed is not None:
        meta.append(f"- **Elapsed:** {run.elapsed:.0f}s")
    if run.scm_revision:
        meta.append(f"- **Revision:** `{run.scm_revision[:12]}`")
    if run.awx_limit:
        meta.append(f"- **Limit:** `{run.awx_limit}`")
    lines += meta + [""]

    # Per-host recap table
    recap = run.recap or []
    if recap:
        lines += ["## Hosts", "", "| host | " + " | ".join(_RECAP_COLS) + " |",
                  "| --- | " + " | ".join(["---"] * len(_RECAP_COLS)) + " |"]
        for h in recap:
            cells = " | ".join(str(h.get(c, 0)) for c in _RECAP_COLS)
            lines.append(f"| {h.get('host', '?')} | {cells} |")
        lines.append("")

    # Path-to-failure: failed task/loop nodes, in run (counter) order, with error excerpts.
    failed_nodes = [
        n for n in sorted(nodes, key=lambda n: n.counter)
        if n.node_type in ("task", "loop") and n.status in statuses.FAIL_STATUSES
    ]
    err_by_node: dict[str, list[tuple[str, str | None]]] = {}
    for r in failed_results:
        err_by_node.setdefault(r.node_id, []).append((r.host, _err_excerpt(r.result)))

    if failed_nodes:
        lines += [f"## Failures ({len(failed_nodes)})", ""]
        for n in failed_nodes:
            path = _node_path(n, by_id)
            hosts = err_by_node.get(n.node_id, [])
            host_n = len({h for h, _ in hosts}) or (n.host_count or 0)
            suffix = f" — failed on {host_n} host{'' if host_n == 1 else 's'}" if host_n else ""
            mod = f" (`{n.action}`)" if n.action else ""
            lines.append(f"- **{path}**{mod}{suffix}")
            for host, excerpt in hosts:
                if excerpt:
                    lines.append(f"  - `{host}`: {excerpt}")
        lines.append("")
    else:
        lines += ["## Failures", "", "No task failures recorded.", ""]

    return "\n".join(lines).rstrip() + "\n"
