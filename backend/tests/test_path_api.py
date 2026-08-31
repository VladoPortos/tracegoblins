import pytest
from httpx import AsyncClient
from sqlalchemy import select
from app.models import Run, RunNode, RunNodeResult, User

pytestmark = pytest.mark.asyncio


async def _member(db):
    """The user `authed_client` is logged in as (created by the make_user fixture)."""
    return await db.scalar(select(User).where(User.email == "member@example.com"))


async def _seed_run(db, *, owner_id):
    run = Run(source="awx", status="changed", owner_user_id=owner_id, team_id=None,
              extra_vars={"target_env": "prod"}, awx_limit="batch_3", scm_revision="a1b9f4c",
              project_id=7, project_name="day2", job_template_id=12)
    db.add(run); await db.flush()
    db.add_all([
        RunNode(run_id=run.id, node_id="root", parent_node_id=None, counter=0, depth=-1,
                node_type="playbook", name="pb", status="ok", child_count=1),
        RunNode(run_id=run.id, node_id="play-1", parent_node_id="root", counter=1, depth=0,
                node_type="play", name="play", status="changed", child_count=2),
        RunNode(run_id=run.id, node_id="t1", parent_node_id="play-1", counter=2, depth=1,
                node_type="task", name="gather", status="ok", action="ansible.builtin.setup",
                host_count=2, child_count=0),
        RunNode(run_id=run.id, node_id="loop1", parent_node_id="play-1", counter=3, depth=1,
                node_type="loop", name="install", status="changed", item_count=2,
                host_count=2, child_count=0, loop_var="item"),
    ])
    db.add_all([
        RunNodeResult(run_id=run.id, node_id="loop1", host="agg", item_index=0,
                      item_value="nginx", status="ok", changed=False,
                      result={"msg": "ok"}),
        RunNodeResult(run_id=run.id, node_id="loop1", host="agg", item_index=1,
                      item_value="curl", status="changed", changed=True),
    ])
    await db.commit()
    return run


async def test_container_status_rolls_up_at_read_time(authed_client: AsyncClient, db):
    """A multi-play run whose play nodes are PERSISTED as 'ok' but contain a failed task must
    render the failing play as 'failed' — the read-time rollup (PT1) backfills without re-ingest."""
    member = await _member(db)
    run = Run(source="awx", status="failed", owner_user_id=member.id, team_id=None)
    db.add(run); await db.flush()
    db.add_all([
        RunNode(run_id=run.id, node_id="root", parent_node_id=None, counter=0, depth=-1,
                node_type="playbook", name="pb", status="ok", child_count=2),
        # two plays so the main view does NOT auto-descend; both persisted as the stale "ok"
        RunNode(run_id=run.id, node_id="p1", parent_node_id="root", counter=1, depth=0,
                node_type="play", name="play one", status="ok", child_count=1),
        RunNode(run_id=run.id, node_id="p2", parent_node_id="root", counter=2, depth=0,
                node_type="play", name="play two", status="ok", child_count=1),
        RunNode(run_id=run.id, node_id="ok-task", parent_node_id="p1", counter=3, depth=1,
                node_type="task", name="fine", status="ok"),
        RunNode(run_id=run.id, node_id="bad-task", parent_node_id="p2", counter=4, depth=1,
                node_type="task", name="boom", status="failed"),
    ])
    await db.commit()
    body = (await authed_client.get(f"/api/runs/{run.id}/tree")).json()
    plays = {n["id"]: n for n in body["nodes"]}
    assert plays["p1"]["status"] == "ok"
    assert plays["p2"]["status"] == "failed"          # rolled up from the failed child
    assert plays["p2"]["has_failures"] is True


async def test_tree_main_view_single_play_descends(authed_client: AsyncClient, db):
    member = await _member(db)
    run = await _seed_run(db, owner_id=member.id)
    r = await authed_client.get(f"/api/runs/{run.id}/tree")
    assert r.status_code == 200
    body = r.json()
    assert body["view"] == {"type": "main"}
    ids = [n["id"] for n in body["nodes"]]
    assert "t1" in ids and "loop1" in ids and "play-1" not in ids   # descended into the single play
    loop = next(n for n in body["nodes"] if n["id"] == "loop1")
    assert loop["type"] == "loop" and loop["enter_to"] == {"type": "loop", "id": "loop1"}
    assert loop["item_count"] == 2 and loop["sub"] == "loop · 2 items"
    assert body["edges"][0]["from"] == "t1" and body["edges"][0]["to"] == "loop1"
    # Task 9 regression guard: plain task nodes must emit ALL nullable fields as explicit null,
    # not omit them — the frontend contract declares them as X|null (present, nullable).
    t1 = next(n for n in body["nodes"] if n["id"] == "t1")
    assert "sub" in t1 and t1["sub"] is None
    assert "enter_to" in t1 and t1["enter_to"] is None
    assert "condition" in t1 and t1["condition"] is None
    assert "branch" in t1 and t1["branch"] is None


async def test_loop_view_synthesizes_item_result(authed_client: AsyncClient, db):
    run = await _seed_run(db, owner_id=(await _member(db)).id)
    r = await authed_client.get(f"/api/runs/{run.id}/tree?root=loop1&iter=1")
    body = r.json()
    assert body["view"] == {"type": "loop", "id": "loop1"}
    types = [n["type"] for n in body["nodes"]]
    assert types == ["loop", "item", "task", "result"]
    item = next(n for n in body["nodes"] if n["type"] == "item")
    assert item["label"] == '= "curl"'                 # iter=1 -> second item
    # FE2: synthetic item/result carry the real loop node_id so the drawer can fetch per-iter results
    result = next(n for n in body["nodes"] if n["type"] == "result")
    assert item["result_node_id"] == "loop1" and result["result_node_id"] == "loop1"


async def test_loop_view_multihost_maps_iter_to_item_not_flat_offset(authed_client: AsyncClient, db):
    """RUNS1: on a 2-item loop across 2 hosts, iter=1 must show ITEM 1 (worst host), not the flat
    (item0,hostB) row — otherwise later items are unreachable."""
    member = await _member(db)
    run = Run(source="awx", status="changed", owner_user_id=member.id)
    db.add(run); await db.flush()
    db.add_all([
        RunNode(run_id=run.id, node_id="root", parent_node_id=None, counter=0, depth=-1,
                node_type="playbook", name="pb", status="ok", child_count=1),
        RunNode(run_id=run.id, node_id="play-1", parent_node_id="root", counter=1, depth=0,
                node_type="play", name="play", status="changed", child_count=1),
        RunNode(run_id=run.id, node_id="loop1", parent_node_id="play-1", counter=2, depth=1,
                node_type="loop", name="install", status="failed", item_count=2, host_count=2),
    ])
    # 2 items × 2 hosts; item 1 failed on hostB
    db.add_all([
        RunNodeResult(run_id=run.id, node_id="loop1", host="a", item_index=0, item_value="nginx", status="ok"),
        RunNodeResult(run_id=run.id, node_id="loop1", host="b", item_index=0, item_value="nginx", status="ok"),
        RunNodeResult(run_id=run.id, node_id="loop1", host="a", item_index=1, item_value="curl", status="ok"),
        RunNodeResult(run_id=run.id, node_id="loop1", host="b", item_index=1, item_value="curl", status="failed"),
    ])
    await db.commit()
    body = (await authed_client.get(f"/api/runs/{run.id}/tree?root=loop1&iter=1")).json()
    item = next(n for n in body["nodes"] if n["type"] == "item")
    result = next(n for n in body["nodes"] if n["type"] == "result")
    assert item["label"] == '= "curl"'      # iter=1 -> item 1 (not item 0 on the 2nd host)
    assert result["status"] == "failed"      # surfaces the worst host for that item


async def test_loop_ok_fail_counts_populated(authed_client: AsyncClient, db):
    """PATH1: ok_count/fail_count must reflect real per-item results, not stay null (the loop
    aggregate + 'N failed' badge are otherwise permanently '0 ok · 0 failed')."""
    member = await _member(db)
    run = Run(source="awx", status="failed", owner_user_id=member.id)
    db.add(run); await db.flush()
    db.add_all([
        RunNode(run_id=run.id, node_id="root", parent_node_id=None, counter=0, depth=-1,
                node_type="playbook", name="pb", status="ok", child_count=1),
        RunNode(run_id=run.id, node_id="play-1", parent_node_id="root", counter=1, depth=0,
                node_type="play", name="play", status="failed", child_count=1),
        RunNode(run_id=run.id, node_id="loop1", parent_node_id="play-1", counter=2, depth=1,
                node_type="loop", name="install", status="failed", item_count=2, host_count=1),
    ])
    db.add_all([
        RunNodeResult(run_id=run.id, node_id="loop1", host="a", item_index=0, item_value="x", status="ok"),
        RunNodeResult(run_id=run.id, node_id="loop1", host="a", item_index=1, item_value="y", status="failed"),
        # the per-host terminal aggregate row (no item_index) must NOT be counted as an extra item
        RunNodeResult(run_id=run.id, node_id="loop1", host="a", item_index=None, status="failed"),
    ])
    await db.commit()
    # main view (single play descends): the loop node card carries the counts
    main = (await authed_client.get(f"/api/runs/{run.id}/tree")).json()
    loop = next(n for n in main["nodes"] if n["id"] == "loop1")
    assert loop["ok_count"] == 1 and loop["fail_count"] == 1   # 2 items, not 3 (terminal row excluded)
    # loop synth view: the loopRoot aggregate too
    lv = (await authed_client.get(f"/api/runs/{run.id}/tree?root=loop1&iter=0")).json()
    lr = next(n for n in lv["nodes"] if n["id"] == "loopRoot")
    assert lr["ok_count"] == 1 and lr["fail_count"] == 1


async def test_tree_emits_is_handler_flag(authed_client: AsyncClient, db):
    """A fired handler node persists is_handler=True and the tree endpoint surfaces it so the
    frontend can badge it; a normal task emits is_handler=False (explicitly present)."""
    member = await _member(db)
    run = Run(source="awx", status="changed", owner_user_id=member.id)
    db.add(run); await db.flush()
    db.add_all([
        RunNode(run_id=run.id, node_id="root", parent_node_id=None, counter=0, depth=-1,
                node_type="playbook", name="pb", status="ok", child_count=1),
        RunNode(run_id=run.id, node_id="play-1", parent_node_id="root", counter=1, depth=0,
                node_type="play", name="play", status="changed", child_count=2),
        RunNode(run_id=run.id, node_id="tmpl", parent_node_id="play-1", counter=2, depth=1,
                node_type="task", name="write config", status="changed",
                action="ansible.builtin.template"),
        RunNode(run_id=run.id, node_id="restart", parent_node_id="play-1", counter=3, depth=1,
                node_type="task", name="restart nginx", status="changed",
                action="ansible.builtin.service", is_handler=True),
    ])
    await db.commit()
    body = (await authed_client.get(f"/api/runs/{run.id}/tree")).json()
    nodes = {n["id"]: n for n in body["nodes"]}
    assert nodes["restart"]["is_handler"] is True
    assert nodes["tmpl"]["is_handler"] is False


async def test_tree_stale_root_is_404_not_main_view(authed_client: AsyncClient, db):
    # RUNS2: a root id that isn't part of this run must 404 (mirror /source), not silently fall back
    run = await _seed_run(db, owner_id=(await _member(db)).id)
    r = await authed_client.get(f"/api/runs/{run.id}/tree?root=does-not-exist")
    assert r.status_code == 404


async def test_results_pagination(authed_client: AsyncClient, db):
    run = await _seed_run(db, owner_id=(await _member(db)).id)
    r = await authed_client.get(f"/api/runs/{run.id}/nodes/loop1/results?offset=0&limit=1")
    body = r.json()
    assert body["total"] == 2 and len(body["results"]) == 1


async def test_inputs(authed_client: AsyncClient, db):
    run = await _seed_run(db, owner_id=(await _member(db)).id)
    r = await authed_client.get(f"/api/runs/{run.id}/inputs")
    body = r.json()
    assert body["extra_vars"] == {"target_env": "prod"} and body["limit"] == "batch_3"
    assert body["scm_revision"] == "a1b9f4c" and body["project_name"] == "day2"


async def test_fork_backfills_from_results_when_isconditional_persisted_false(authed_client: AsyncClient, db):
    """Real AWX persists is_conditional=False; the read path must re-derive a fork from divergent
    results so already-ingested runs get decision branches without re-sync (PT2 backfill)."""
    member = await _member(db)
    run = Run(source="awx", status="ok", owner_user_id=member.id)
    db.add(run); await db.flush()
    db.add_all([
        RunNode(run_id=run.id, node_id="root", parent_node_id=None, counter=0, depth=-1,
                node_type="playbook", name="pb", status="ok", child_count=1),
        RunNode(run_id=run.id, node_id="play-1", parent_node_id="root", counter=1, depth=0,
                node_type="play", name="play", status="ok", child_count=2),
        # is_conditional PERSISTED FALSE (as real AWX does), divergent results below
        RunNode(run_id=run.id, node_id="deb", parent_node_id="play-1", counter=2, depth=1,
                node_type="task", name="apt", status="ok", is_conditional=False),
        RunNode(run_id=run.id, node_id="rh", parent_node_id="play-1", counter=3, depth=1,
                node_type="task", name="yum", status="ok", is_conditional=False),
    ])
    db.add_all([
        RunNodeResult(run_id=run.id, node_id="deb", host="d1", status="ok"),
        RunNodeResult(run_id=run.id, node_id="deb", host="r1", status="skipped"),
        RunNodeResult(run_id=run.id, node_id="rh", host="d1", status="skipped"),
        RunNodeResult(run_id=run.id, node_id="rh", host="r1", status="ok"),
    ])
    await db.commit()
    body = (await authed_client.get(f"/api/runs/{run.id}/tree")).json()
    assert any(n["type"] == "when" for n in body["nodes"]), "fork must be synthesized from results"
    deb = next(n for n in body["nodes"] if n["id"] == "deb")
    assert deb["is_conditional"] is True and deb["branch"] == "deb"


async def test_never_run_note_on_multiplay_main_view(authed_client: AsyncClient, db):
    """A multi-play main view can't anchor ghosts (plays have no source line) — instead of silently
    showing nothing, the toggle must return a hint to drill into a play (NR3)."""
    member = await _member(db)
    run = Run(source="awx", status="ok", owner_user_id=member.id)
    db.add(run); await db.flush()
    db.add_all([
        RunNode(run_id=run.id, node_id="root", parent_node_id=None, counter=0, depth=-1,
                node_type="playbook", name="pb", status="ok", child_count=2),
        RunNode(run_id=run.id, node_id="p1", parent_node_id="root", counter=1, depth=0,
                node_type="play", name="play one", status="ok", child_count=1),
        RunNode(run_id=run.id, node_id="p2", parent_node_id="root", counter=2, depth=0,
                node_type="play", name="play two", status="ok", child_count=1),
    ])
    await db.commit()
    body = (await authed_client.get(f"/api/runs/{run.id}/tree?never_run=1")).json()
    assert body["never_run_note"] and "play" in body["never_run_note"].lower()
    # without the toggle there is no note
    plain = (await authed_client.get(f"/api/runs/{run.id}/tree")).json()
    assert plain["never_run_note"] is None


async def test_run_summary_endpoint_markdown(authed_client: AsyncClient, db):
    """GET /runs/{id}/summary returns a Markdown run summary with the failing path + error excerpt."""
    member = await _member(db)
    run = Run(source="awx", status="failed", owner_user_id=member.id, awx_job_id="999",
              template_name="Deploy app", host_count=1,
              recap=[{"host": "h1", "ok": 2, "changed": 0, "failed": 1, "unreachable": 0, "skipped": 0}])
    db.add(run); await db.flush()
    db.add_all([
        RunNode(run_id=run.id, node_id="root", parent_node_id=None, counter=0, depth=-1,
                node_type="playbook", name="pb", status="failed", child_count=1),
        RunNode(run_id=run.id, node_id="play-1", parent_node_id="root", counter=1, depth=0,
                node_type="play", name="Main", status="failed", child_count=1),
        RunNode(run_id=run.id, node_id="boom", parent_node_id="play-1", counter=2, depth=1,
                node_type="task", name="do thing", status="failed", action="ansible.builtin.command",
                host_count=1),
    ])
    db.add(RunNodeResult(run_id=run.id, node_id="boom", host="h1", status="failed",
                         result={"msg": "command not found: foobar"}))
    await db.commit()
    r = await authed_client.get(f"/api/runs/{run.id}/summary")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/plain")
    body = r.text
    assert "# Run summary: Deploy app" in body
    assert "**Job:** #999" in body
    assert "| h1 |" in body
    assert "Main › do thing" in body
    assert "command not found: foobar" in body


async def test_run_summary_404_when_not_visible(authed_client: AsyncClient, db):
    run = await _seed_run(db, owner_id=None)   # owner-less, unshared -> not visible to member
    r = await authed_client.get(f"/api/runs/{run.id}/summary")
    assert r.status_code == 404


async def test_tree_404_when_not_visible(authed_client: AsyncClient, db):
    run = await _seed_run(db, owner_id=None)   # owner-less, unshared -> not visible to member
    r = await authed_client.get(f"/api/runs/{run.id}/tree")
    assert r.status_code == 404


async def test_tree_synthesizes_when_fork_for_disjoint_conditionals(authed_client: AsyncClient, db):
    member = await _member(db)
    run = Run(source="awx", status="ok", owner_user_id=member.id)
    db.add(run); await db.flush()
    db.add_all([
        RunNode(run_id=run.id, node_id="root", parent_node_id=None, counter=0, depth=-1,
                node_type="playbook", name="pb", status="ok", child_count=1),
        RunNode(run_id=run.id, node_id="play-1", parent_node_id="root", counter=1, depth=0,
                node_type="play", name="play", status="ok", child_count=2),
        RunNode(run_id=run.id, node_id="yum", parent_node_id="play-1", counter=2, depth=1,
                node_type="task", name="yum repo", status="ok", is_conditional=True, host_count=2),
        RunNode(run_id=run.id, node_id="choco", parent_node_id="play-1", counter=3, depth=1,
                node_type="task", name="choco repo", status="ok", is_conditional=True, host_count=1),
    ])
    db.add_all([
        RunNodeResult(run_id=run.id, node_id="yum", host="rhel1", status="ok"),
        RunNodeResult(run_id=run.id, node_id="yum", host="win1", status="skipped"),
        RunNodeResult(run_id=run.id, node_id="choco", host="rhel1", status="skipped"),
        RunNodeResult(run_id=run.id, node_id="choco", host="win1", status="ok"),
    ])
    await db.commit()
    body = (await authed_client.get(f"/api/runs/{run.id}/tree")).json()
    assert any(n["type"] == "when" for n in body["nodes"])
    yum = next(n for n in body["nodes"] if n["id"] == "yum")
    assert yum["branch"] == "yum"
    assert any(e["from"].startswith("when:") and e["to"] == "yum" for e in body["edges"])
