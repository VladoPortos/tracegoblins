from __future__ import annotations

import uuid

from app.awx.client import JobDetail
from app.core.clock import parse_iso as _parse_iso
from app.logparser import ParsedTree
from app.models import Run, RunNode, RunNodeResult


def build_run_nodes(tree: ParsedTree, run_id: uuid.UUID) -> tuple[list[RunNode], list[RunNodeResult]]:
    """Map a ParsedTree (from build_tree) to ORM rows for persistence.

    Pure-ish: no DB I/O, no side effects. _parse_iso converts ISO strings to
    aware datetimes and safely returns None for absent/unparseable values.
    """
    nodes = [
        RunNode(
            run_id=run_id, node_id=n.node_id, parent_node_id=n.parent_id, counter=n.counter,
            depth=n.depth, node_type=n.node_type, name=n.name, action=n.action,
            task_path=n.task_path, ansible_uuid=n.ansible_uuid, is_conditional=n.is_conditional,
            is_handler=n.is_handler,
            when_expr=n.when_expr, loop_var=n.loop_var, status=n.status, changed=n.changed,
            host_count=n.host_count, item_count=n.item_count, child_count=n.child_count,
            started_at=_parse_iso(n.started_at), duration_s=n.duration_s, args=n.args,
        )
        for n in tree.nodes
    ]
    results = [
        RunNodeResult(
            run_id=run_id, node_id=r.node_id, host=r.host, item_index=r.item_index,
            item_value=r.item_value, status=r.status, changed=r.changed, result=r.result,
            skip_reason=r.skip_reason, false_condition=r.false_condition,
            started_at=_parse_iso(r.started_at), ended_at=_parse_iso(r.ended_at),
            duration_s=r.duration_s,
        )
        for r in tree.results
    ]
    return nodes, results


def apply_job_detail(run: Run, detail: JobDetail) -> None:
    """Set the 7 Run input columns from a JobDetail (AWX GET /jobs/{id}/ response)."""
    run.extra_vars = detail.extra_vars or None
    run.awx_limit = detail.limit
    run.scm_revision = detail.scm_revision
    run.project_id = detail.project_id
    run.project_name = detail.project_name
    run.job_template_id = detail.job_template_id
    run.survey = detail.survey
