"""Real-fixture end-to-end integration test for the Run Path Explorer pipeline.

Loads the real AWX fixture (job_743_events.json — 861 events, 3 plays, 25 includes,
28 loop items) and drives it through the full pipeline:

    build_tree → build_run_nodes → DB persist → API endpoints

Proves parser → storage → API works on REAL AWX data without Docker or a real AWX
controller. All assertions are concrete values derived from what build_tree actually
produces from the fixture (no vacuous "assert len > 0" guards).

Fixture characteristics (verified by inspecting the fixture before writing tests):
- 288 nodes total (1 playbook root + 3 plays + 22 includes + 15 loops + 247 tasks)
- 308 results total
- 3 plays: multi-play job so main view returns the 3 plays (NOT descended into one)
- Best loop: 3a4280f5-5274-169e-f906-0000000007f9 (item_count=7, status=ok,
  "Define collected managed option variables")
  → 8 results total (7 item-indexed + 1 terminal)
- First include: inc:3a4280f5-5274-169e-f906-000000000002:tasks/resolve_organization.yml
  (child_count=8)
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.awx.client import JobDetail
from app.logparser import build_tree
from app.models import Run, RunNode, RunNodeResult, User
from app.services.run_tree import apply_job_detail, build_run_nodes

pytestmark = pytest.mark.asyncio

# ---------------------------------------------------------------------------
# Fixture path
# ---------------------------------------------------------------------------

_FIXTURE = Path(__file__).parent / "fixtures" / "awx" / "job_743_events.json"

# Stable node ids derived from inspecting build_tree(job_743) output.
# These are task_uuid values from the AWX event stream — stable across parser runs.
_LOOP_ID = "3a4280f5-5274-169e-f906-0000000007f9"   # "Define collected managed option variables"
                                                      # item_count=7, status=ok
_PLAY1_ID = "3a4280f5-5274-169e-f906-000000000002"   # "Day2Actions entrypoint" (child_count=45)
_INC1_ID = (
    "inc:3a4280f5-5274-169e-f906-000000000002"
    ":tasks/resolve_organization.yml"
)                                                     # first include container, child_count=8


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _member(db) -> User:
    """The user authed_client is authenticated as."""
    return await db.scalar(select(User).where(User.email == "member@example.com"))


async def _build_and_persist_run(db) -> Run:
    """Parse the real fixture, persist all nodes + results, set input columns."""
    events = json.loads(_FIXTURE.read_text())
    tree = build_tree(events)

    # Sanity checks on parser output so test failures are diagnosable
    assert len(tree.nodes) == 288, f"Expected 288 nodes, got {len(tree.nodes)}"
    assert len(tree.results) == 308, f"Expected 308 results, got {len(tree.results)}"
    loop_nodes = [n for n in tree.nodes if n.node_type == "loop"]
    assert len(loop_nodes) == 15, f"Expected 15 loop nodes, got {len(loop_nodes)}"
    include_nodes = [n for n in tree.nodes if n.node_type == "include"]
    assert len(include_nodes) == 22, f"Expected 22 include nodes, got {len(include_nodes)}"

    member = await _member(db)
    run = Run(source="awx", status="ok", owner_user_id=member.id)
    db.add(run)
    await db.flush()

    nodes, results = build_run_nodes(tree, run.id)
    db.add_all(nodes)
    db.add_all(results)
    await db.flush()

    # Set input columns via apply_job_detail (mirrors the real sync pipeline)
    detail = JobDetail(
        extra_vars={"target_env": "staging", "deploy_version": "2.3.1"},
        limit="batch_group",
        scm_revision="d4e5f6a",
        project_id=42,
        project_name="day2-ops",
        job_template_id=99,
        survey=None,
    )
    apply_job_detail(run, detail)
    await db.commit()
    return run


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

async def test_real_fixture_main_view(authed_client: AsyncClient, db):
    """Main view returns the 3 real play nodes (multi-play → no descent).

    The fixture has 3 plays, so the API does NOT auto-descend into a single play;
    it returns the 3 play nodes as the top-level band.
    """
    run = await _build_and_persist_run(db)
    r = await authed_client.get(f"/api/runs/{run.id}/tree")
    assert r.status_code == 200
    body = r.json()

    assert body["view"] == {"type": "main"}
    node_ids = {n["id"] for n in body["nodes"]}
    node_types = [n["type"] for n in body["nodes"]]

    # 3 play nodes at the top — NOT tasks (multi-play job)
    assert node_ids == {
        "3a4280f5-5274-169e-f906-000000000002",
        "3a4280f5-5274-169e-f906-000000000028",
        "3a4280f5-5274-169e-f906-000000000031",
    }
    assert node_types.count("play") == 3

    # Linear edges connect the 3 plays in counter order
    assert len(body["edges"]) == 2

    # Plays with children are enterable containers (enter_to = {type: container, id: <play_id>})
    play1 = next(n for n in body["nodes"] if n["id"] == _PLAY1_ID)
    assert play1["label"] == "Day2Actions entrypoint"
    assert play1["enter_to"] == {"type": "container", "id": _PLAY1_ID}  # play is now enterable

    # Contract: nullable fields present AND explicitly null (not merely absent)
    assert play1["sub"] is None and play1["condition"] is None and play1["branch"] is None


async def test_real_fixture_container_view_has_include_nodes(authed_client: AsyncClient, db):
    """Drilling into the first play returns include + task nodes with enter_to on includes."""
    run = await _build_and_persist_run(db)
    r = await authed_client.get(f"/api/runs/{run.id}/tree?root={_PLAY1_ID}")
    assert r.status_code == 200
    body = r.json()

    assert body["view"] == {"type": "container", "id": _PLAY1_ID}
    node_types = [n["type"] for n in body["nodes"]]

    # Play 1 has 45 children: includes + tasks
    assert len(body["nodes"]) == 45

    # Include nodes are present in the container view
    assert "include" in node_types
    assert "task" in node_types

    # The first include node has enter_to = {type: 'container', id: inc_id}
    inc1 = next((n for n in body["nodes"] if n["id"] == _INC1_ID), None)
    assert inc1 is not None, f"Include node {_INC1_ID!r} not found in container view"
    assert inc1["enter_to"] == {"type": "container", "id": _INC1_ID}
    assert inc1["label"] == "resolve_organization.yml"
    assert inc1["type"] == "include"

    # Loop node appears in this play's container children — play 1 has exactly one direct loop child.
    # Assert unconditionally: the loop is present and has enter_to = {type: 'loop', id: <loop_id>}.
    _LOOP_IN_PLAY1 = "3a4280f5-5274-169e-f906-00000000000e"  # "Process managed options list"
    loop_in_play = next((n for n in body["nodes"] if n["id"] == _LOOP_IN_PLAY1), None)
    assert loop_in_play is not None, f"Loop {_LOOP_IN_PLAY1!r} not found in play1 container view"
    assert loop_in_play["enter_to"] == {"type": "loop", "id": _LOOP_IN_PLAY1}


async def test_real_fixture_loop_view_synthesizes_item_nodes(authed_client: AsyncClient, db):
    """Loop view for iter=0 synthesizes [loop, item, task, result] from real fixture data.

    Uses the 7-item loop "Define collected managed option variables" (status=ok).
    The first item value is a dict {'key': 'step', 'value': 'step1'}.
    """
    run = await _build_and_persist_run(db)
    r = await authed_client.get(f"/api/runs/{run.id}/tree?root={_LOOP_ID}&iter=0")
    assert r.status_code == 200
    body = r.json()

    assert body["view"] == {"type": "loop", "id": _LOOP_ID}
    types = [n["type"] for n in body["nodes"]]
    assert types == ["loop", "item", "task", "result"]

    loop_node = body["nodes"][0]
    assert loop_node["id"] == "loopRoot"
    assert loop_node["item_count"] == 7

    item_node = body["nodes"][1]
    assert item_node["id"] == "item"
    assert item_node["type"] == "item"
    # iter=0 → first item; value is a dict so rendered as string repr
    assert "iteration 1" in (item_node["sub"] or "")

    # 3 linear edges connecting the 4 nodes
    assert len(body["edges"]) == 3
    assert body["edges"][0]["from"] == "loopRoot"
    assert body["edges"][0]["to"] == "item"
    assert body["edges"][2]["to"] == "result"


async def test_real_fixture_loop_view_iter1(authed_client: AsyncClient, db):
    """iter=1 returns second item result (different item_value from iter=0)."""
    run = await _build_and_persist_run(db)
    r0 = await authed_client.get(f"/api/runs/{run.id}/tree?root={_LOOP_ID}&iter=0")
    r1 = await authed_client.get(f"/api/runs/{run.id}/tree?root={_LOOP_ID}&iter=1")
    assert r0.status_code == 200 and r1.status_code == 200
    item0 = next(n for n in r0.json()["nodes"] if n["type"] == "item")
    item1 = next(n for n in r1.json()["nodes"] if n["type"] == "item")
    assert item0["label"] != item1["label"], "iter=0 and iter=1 should yield different item labels"


async def test_real_fixture_node_results_pagination(authed_client: AsyncClient, db):
    """GET /nodes/{id}/results returns all 8 results for the 7-item loop (7 item + 1 terminal).

    Pagination: limit=3 returns 3 results but total=8.
    """
    run = await _build_and_persist_run(db)

    # Full count
    r_all = await authed_client.get(f"/api/runs/{run.id}/nodes/{_LOOP_ID}/results")
    assert r_all.status_code == 200
    body_all = r_all.json()
    assert body_all["total"] == 8   # 7 item-indexed + 1 terminal runner_on_ok
    assert len(body_all["results"]) == 8

    # Paginated: page of 3
    r_page = await authed_client.get(
        f"/api/runs/{run.id}/nodes/{_LOOP_ID}/results?offset=0&limit=3"
    )
    assert r_page.status_code == 200
    body_page = r_page.json()
    assert body_page["total"] == 8
    assert len(body_page["results"]) == 3

    # item-indexed results have item_index set
    item_results = [r for r in body_all["results"] if r["item_index"] is not None]
    assert len(item_results) == 7
    indices = sorted(r["item_index"] for r in item_results)
    assert indices == list(range(7))


async def test_real_fixture_inputs_endpoint(authed_client: AsyncClient, db):
    """GET /inputs returns the JobDetail columns we set via apply_job_detail."""
    run = await _build_and_persist_run(db)
    r = await authed_client.get(f"/api/runs/{run.id}/inputs")
    assert r.status_code == 200
    body = r.json()
    assert body["extra_vars"] == {"target_env": "staging", "deploy_version": "2.3.1"}
    assert body["limit"] == "batch_group"
    assert body["scm_revision"] == "d4e5f6a"
    assert body["project_name"] == "day2-ops"
    assert body["project_id"] == 42
    # W3: survey is part of RunInputsOut — helper sets it to None, assert explicit null
    assert body["survey"] is None
    # job_template_id is not exposed via /inputs (not in RunInputsOut) but is persisted on the run
    refreshed = await db.get(Run, run.id)
    assert refreshed.job_template_id == 99


async def test_real_fixture_tree_not_visible_to_unrelated_user(authed_client: AsyncClient, db):
    """A run owned by None (no owner, no share) is 404 to the authed member."""
    events = json.loads(_FIXTURE.read_text())
    tree = build_tree(events)
    run = Run(source="awx", status="ok", owner_user_id=None)
    db.add(run)
    await db.flush()
    nodes, results = build_run_nodes(tree, run.id)
    db.add_all(nodes)
    db.add_all(results)
    await db.commit()

    r = await authed_client.get(f"/api/runs/{run.id}/tree")
    assert r.status_code == 404


async def test_fork_synthesis_pipeline_integration(authed_client: AsyncClient, db):
    """Fork synthesis (synthesize_forks / taken_hosts) is exercised through the full
    build_tree → build_run_nodes → DB → GET /runs/{id}/tree pipeline.

    Scenario: one play with two CONDITIONAL sibling tasks (OS-branching pattern):
      - "yum repo"   → runner_on_ok on rhel1+rhel2; runner_on_skipped (false_condition) on win1
      - "choco repo" → runner_on_ok on win1;         runner_on_skipped (false_condition) on rhel1+rhel2
    The two taken-host sets are DISJOINT → synthesize_forks must create a synthetic `when` node
    and branch both tasks off it, each carrying the correct taken_hosts list.
    """
    play_uuid  = "pipe-play-0001"
    yum_uuid   = "pipe-task-yum1"
    choco_uuid = "pipe-task-cho1"

    events = [
        {
            "counter": 1, "event": "playbook_on_play_start",
            "event_data": {"play_uuid": play_uuid, "play": "OS bootstrap",
                           "task_path": "site.yml:1"},
        },
        # yum task start
        {
            "counter": 2, "event": "playbook_on_task_start",
            "event_data": {
                "task_uuid": yum_uuid, "task": "yum repo", "task_action": "ansible.builtin.yum",
                "task_path": "tasks/linux.yml:5", "is_conditional": True,
            },
        },
        # yum results: ok on rhel1+rhel2, skipped on win1
        {
            "counter": 3, "event": "runner_on_ok",
            "event_data": {"task_uuid": yum_uuid, "host": "rhel1",
                           "res": {"changed": False}, "duration": 1.2},
        },
        {
            "counter": 4, "event": "runner_on_ok",
            "event_data": {"task_uuid": yum_uuid, "host": "rhel2",
                           "res": {"changed": False}, "duration": 1.1},
        },
        {
            "counter": 5, "event": "runner_on_skipped",
            "event_data": {"task_uuid": yum_uuid, "host": "win1",
                           "res": {"false_condition": "ansible_os_family == 'RedHat'"}},
        },
        # choco task start
        {
            "counter": 6, "event": "playbook_on_task_start",
            "event_data": {
                "task_uuid": choco_uuid, "task": "choco repo", "task_action": "chocolatey.chocolatey.win_chocolatey",
                "task_path": "tasks/windows.yml:3", "is_conditional": True,
            },
        },
        # choco results: ok on win1, skipped on rhel1+rhel2
        {
            "counter": 7, "event": "runner_on_ok",
            "event_data": {"task_uuid": choco_uuid, "host": "win1",
                           "res": {"changed": True}, "duration": 2.5},
        },
        {
            "counter": 8, "event": "runner_on_skipped",
            "event_data": {"task_uuid": choco_uuid, "host": "rhel1",
                           "res": {"false_condition": "ansible_os_family == 'Windows'"}},
        },
        {
            "counter": 9, "event": "runner_on_skipped",
            "event_data": {"task_uuid": choco_uuid, "host": "rhel2",
                           "res": {"false_condition": "ansible_os_family == 'Windows'"}},
        },
    ]

    # Build & persist through the real pipeline (same pattern as _build_and_persist_run)
    tree = build_tree(events)

    member = await db.scalar(select(User).where(User.email == "member@example.com"))
    run = Run(source="awx", status="ok", owner_user_id=member.id)
    db.add(run)
    await db.flush()

    nodes, results = build_run_nodes(tree, run.id)
    db.add_all(nodes)
    db.add_all(results)
    await db.commit()

    # Single-play job → API auto-descends into the play's children
    r = await authed_client.get(f"/api/runs/{run.id}/tree")
    assert r.status_code == 200
    body = r.json()

    node_types = [n["type"] for n in body["nodes"]]
    node_by_id = {n["id"]: n for n in body["nodes"]}

    # A synthetic `when` node must have been inserted
    when_nodes = [n for n in body["nodes"] if n["type"] == "when"]
    assert len(when_nodes) == 1, f"Expected 1 when node, got {when_nodes}"
    when_node = when_nodes[0]
    assert when_node["is_conditional"] is True
    assert when_node["branch"] is None  # the when hub itself has no branch key

    # Both conditional tasks are present as branch nodes
    assert yum_uuid in node_by_id, "yum task not in response nodes"
    assert choco_uuid in node_by_id, "choco task not in response nodes"
    yum_node   = node_by_id[yum_uuid]
    choco_node = node_by_id[choco_uuid]

    # Each branch node carries its own branch key
    assert yum_node["branch"]   == yum_uuid
    assert choco_node["branch"] == choco_uuid

    # Taken-host sets are DISJOINT and correct
    # _taken_hosts only includes non-skipped results, so rhel1+rhel2 ran yum, win1 ran choco
    assert sorted(yum_node["taken_hosts"])   == ["rhel1", "rhel2"]
    assert sorted(choco_node["taken_hosts"]) == ["win1"]

    # Edge set: when→yum (branch=yum_uuid), when→choco (branch=choco_uuid)
    edges_from_when = [e for e in body["edges"] if e["from"] == when_node["id"]]
    edge_targets = {e["to"] for e in edges_from_when}
    assert yum_uuid   in edge_targets, "Missing when→yum edge"
    assert choco_uuid in edge_targets, "Missing when→choco edge"
    # Each of those edges carries the branch tag
    for e in edges_from_when:
        assert e["branch"] is not None, "when→branch edge must carry a branch tag"
