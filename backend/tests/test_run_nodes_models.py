import uuid
import pytest
from sqlalchemy import select
from app.models import Run, RunNode, RunNodeResult

pytestmark = pytest.mark.asyncio


async def test_persist_and_query_run_nodes(db):
    run = Run(source="awx", status="failed", extra_vars={"target_env": "prod"},
              awx_limit="batch_3", scm_revision="a1b9f4c", project_id=7,
              project_name="day2", job_template_id=12, survey={"ticket": "CHG1"})
    db.add(run)
    await db.flush()
    node = RunNode(run_id=run.id, node_id="n1", parent_node_id=None, counter=1, depth=0,
                   node_type="loop", name="install", status="changed", item_count=50,
                   child_count=0, host_count=50, is_conditional=False, changed=True)
    db.add(node)
    db.add(RunNodeResult(run_id=run.id, node_id="n1", host="aggregate", item_index=13,
                         item_value="kernel-devel", status="failed", changed=False))
    await db.flush()
    nodes = (await db.execute(select(RunNode).where(RunNode.run_id == run.id))).scalars().all()
    results = (await db.execute(select(RunNodeResult).where(RunNodeResult.run_id == run.id))).scalars().all()
    assert len(nodes) == 1 and nodes[0].item_count == 50
    assert len(results) == 1 and results[0].item_value == "kernel-devel"
    assert run.extra_vars["target_env"] == "prod" and run.awx_limit == "batch_3"
