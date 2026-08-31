import json
from pathlib import Path

from app.logparser import ParsedTree, TreeNode, TreeResult, build_tree

FIXTURES = Path(__file__).parent.parent / "fixtures" / "awx"


def _events(name: str) -> list[dict]:
    return json.loads((FIXTURES / name).read_text())


def test_dataclasses_construct_with_defaults():
    n = TreeNode(node_id="n1", parent_id=None, counter=1, depth=0, node_type="play", name="p")
    assert n.status == "ok" and n.host_count == 0 and n.args is None
    r = TreeResult(node_id="n1", host="h1")
    assert r.item_index is None and r.changed is False
    t = ParsedTree()
    assert t.nodes == [] and t.results == []


def test_core_emits_root_play_and_tasks_745():
    tree = build_tree(_events("job_745_events.json"))
    roots = [n for n in tree.nodes if n.node_type == "playbook"]
    plays = [n for n in tree.nodes if n.node_type == "play"]
    tasks = [n for n in tree.nodes if n.node_type == "task"]
    assert len(roots) == 1 and roots[0].parent_id is None
    assert len(plays) == 1 and plays[0].name == "Day2Actions entrypoint"
    assert plays[0].parent_id == roots[0].node_id and plays[0].depth == 0
    # every task is parented to a play and ordered by counter
    assert tasks, "expected task nodes"
    assert all(t.parent_id is not None for t in tasks)
    counters = [t.counter for t in tasks]
    assert counters == sorted(counters)


def test_core_captures_action_path_conditional():
    tree = build_tree(_events("job_745_events.json"))
    disp = next(n for n in tree.nodes if n.name == "Display AWX job info")
    assert disp.action == "ansible.builtin.debug"
    assert disp.task_path == "main.yaml:20"           # /runner/project/ stripped
    assert disp.is_conditional is False
    assert disp.ansible_uuid and disp.ansible_uuid.endswith("000000000004")


def test_core_malformed_events_do_not_raise():
    tree = build_tree([{"event": None}, {}, {"event": "verbose"}])
    # only the synthetic root, no plays/tasks
    assert [n.node_type for n in tree.nodes] == ["playbook"]


# ---------------------------------------------------------------------------
# Task 3: container reconstruction (include + role grouping, depth, child_count)
# ---------------------------------------------------------------------------

def test_include_container_groups_children_745():
    tree = build_tree(_events("job_745_events.json"))
    includes = [n for n in tree.nodes if n.node_type == "include"]
    assert includes, "expected at least one include container"
    # the resolve_organization include groups the tasks defined in that file
    org = next((n for n in includes if "resolve_organization" in n.name), None)
    assert org is not None
    kids = [n for n in tree.nodes if n.parent_id == org.node_id]
    assert kids, "include container has children"
    assert org.child_count == len(kids)
    assert all(k.depth == org.depth + 1 for k in kids)


def test_every_node_has_consistent_child_count():
    tree = build_tree(_events("job_745_events.json"))
    by_id = {n.node_id: n for n in tree.nodes}
    counts: dict[str, int] = {}
    for n in tree.nodes:
        if n.parent_id is not None:
            counts[n.parent_id] = counts.get(n.parent_id, 0) + 1
    for nid, node in by_id.items():
        assert node.child_count == counts.get(nid, 0)


def test_role_container_groups_children():
    """Synthetic test: tasks carrying event_data.role are grouped under a role container."""
    play_uuid = "play-uuid-001"
    events = [
        {
            "counter": 1,
            "event": "playbook_on_play_start",
            "event_data": {"play_uuid": play_uuid, "play": "Test Play"},
        },
        {
            "counter": 2,
            "event": "playbook_on_task_start",
            "event_data": {
                "task_uuid": "task-uuid-001",
                "task": "First role task",
                "task_action": "ansible.builtin.debug",
                "role": "myrole",
            },
        },
        {
            "counter": 3,
            "event": "playbook_on_task_start",
            "event_data": {
                "task_uuid": "task-uuid-002",
                "task": "Second role task",
                "task_action": "ansible.builtin.debug",
                "role": "myrole",
            },
        },
    ]
    tree = build_tree(events)

    roles = [n for n in tree.nodes if n.node_type == "role"]
    assert len(roles) == 1, "exactly one role container expected"
    role_node = roles[0]
    assert role_node.name == "myrole"

    kids = [n for n in tree.nodes if n.parent_id == role_node.node_id]
    assert len(kids) == 2, "both tasks must be parented to the role container"
    assert role_node.child_count == 2

    task_depth = role_node.depth + 1
    assert all(k.depth == task_depth for k in kids)


# ---------------------------------------------------------------------------
# Task 4: results, loops, conditionals, durations
# ---------------------------------------------------------------------------

def test_container_status_rolls_up_to_failed_745():
    # job_745 contains a failed task; its enclosing play AND the playbook root must roll up
    # to "failed" (PT1) rather than the default "ok".
    tree = build_tree(_events("job_745_events.json"))
    failed = [n for n in tree.nodes if n.status == "failed"]
    assert any(n.node_type == "task" for n in failed), "expected a failed task in the fixture"
    play = next(n for n in tree.nodes if n.node_type == "play")
    root = next(n for n in tree.nodes if n.node_type == "playbook")
    assert play.status == "failed"
    assert root.status == "failed"


def test_failed_task_745_has_failed_result_and_status():
    tree = build_tree(_events("job_745_events.json"))
    node = next(n for n in tree.nodes if n.name == "Ensure target VM exists")
    assert node.status == "failed"
    res = [r for r in tree.results if r.node_id == node.node_id]
    assert any(r.status == "failed" for r in res)
    failed = next(r for r in res if r.status == "failed")
    assert failed.host == "localhost"
    assert "not found in CDB" in (failed.result or {}).get("msg", "")


def test_skipped_task_745_carries_status_skipped():
    tree = build_tree(_events("job_745_events.json"))
    skips = [r for r in tree.results if r.status == "skipped"]
    assert skips, "expected skipped results"


def test_is_conditional_derived_from_host_divergence():
    """AWX never sets event_data.is_conditional (always False), so we derive it: a task that ran
    on some hosts and skipped on others is conditional (PT2). A single-host skip is NOT a fork."""
    play_uuid, t_div, t_skip = "play-c", "task-div", "task-skip"
    events = [
        {"counter": 1, "event": "playbook_on_play_start",
         "event_data": {"play_uuid": play_uuid, "play": "P"}},
        {"counter": 2, "event": "playbook_on_task_start",
         "event_data": {"task_uuid": t_div, "task": "divergent", "task_action": "debug",
                        "is_conditional": False}},
        {"counter": 3, "event": "runner_on_ok",
         "event_data": {"task_uuid": t_div, "host": "h1", "res": {}}},
        {"counter": 4, "event": "runner_on_skipped",
         "event_data": {"task_uuid": t_div, "host": "h2", "res": {}}},
        {"counter": 5, "event": "playbook_on_task_start",
         "event_data": {"task_uuid": t_skip, "task": "all-skip", "task_action": "debug",
                        "is_conditional": False}},
        {"counter": 6, "event": "runner_on_skipped",
         "event_data": {"task_uuid": t_skip, "host": "h1", "res": {}}},
    ]
    tree = build_tree(events)
    div = next(n for n in tree.nodes if n.node_id == t_div)
    skip = next(n for n in tree.nodes if n.node_id == t_skip)
    assert div.is_conditional is True   # ran on h1, skipped on h2 → a real decision
    assert skip.is_conditional is False  # only host skipped → no fork (still an inline skipped node)


def test_handler_task_start_marks_node_is_handler():
    """A node born from playbook_on_handler_task_start (a notified handler that FIRED) carries
    is_handler=True; a normal playbook_on_task_start node does not."""
    play_uuid = "play-h"
    events = [
        {"counter": 1, "event": "playbook_on_play_start",
         "event_data": {"play_uuid": play_uuid, "play": "P"}},
        {"counter": 2, "event": "playbook_on_task_start",
         "event_data": {"task_uuid": "t-normal", "task": "write config",
                        "task_action": "ansible.builtin.template"}},
        {"counter": 3, "event": "playbook_on_handler_task_start",
         "event_data": {"task_uuid": "t-handler", "task": "restart nginx",
                        "task_action": "ansible.builtin.service"}},
    ]
    tree = build_tree(events)
    normal = next(n for n in tree.nodes if n.node_id == "t-normal")
    handler = next(n for n in tree.nodes if n.node_id == "t-handler")
    assert normal.is_handler is False
    assert handler.is_handler is True
    assert handler.node_type == "task"  # still a task node, just flagged


def test_loop_node_743_item_aggregation():
    tree = build_tree(_events("job_743_events.json"))
    loops = [n for n in tree.nodes if n.node_type == "loop"]
    assert loops, "expected at least one loop node"
    lp = loops[0]
    items = [r for r in tree.results if r.node_id == lp.node_id and r.item_index is not None]
    assert lp.item_count == len({r.item_index for r in items})


def test_multihost_loop_item_count_is_per_host_not_global():
    """A K-item loop running on H hosts must have item_count=K, not H*K.

    Builds a synthetic event stream: one loop task with 3 items (a, b, c)
    running on two hosts (h1, h2) — 6 runner_item_on_ok events in total.
    Asserts:
      - loop node item_count == 3  (not 6)
      - each host's item_index values == {0, 1, 2}
    Single-host loops are unchanged: H=1 gives per-host count == global count.
    """
    play_uuid = "play-mh-001"
    task_uuid = "task-mh-001"
    events = [
        {
            "counter": 1, "event": "playbook_on_play_start",
            "event_data": {"play_uuid": play_uuid, "play": "Multi-host loop play"},
        },
        {
            "counter": 2, "event": "playbook_on_task_start",
            "event_data": {"task_uuid": task_uuid, "task": "Install packages",
                           "task_action": "ansible.builtin.package"},
        },
    ]
    # 3 items × 2 hosts = 6 runner_item_on_ok events
    counter = 3
    for host in ("h1", "h2"):
        for item in ("a", "b", "c"):
            events.append({
                "counter": counter, "event": "runner_item_on_ok",
                "event_data": {
                    "task_uuid": task_uuid, "host": host,
                    "res": {"item": item, "changed": False},
                },
            })
            counter += 1
    # terminal runner_on_ok per host
    for host in ("h1", "h2"):
        events.append({
            "counter": counter, "event": "runner_on_ok",
            "event_data": {"task_uuid": task_uuid, "host": host, "res": {}},
        })
        counter += 1

    tree = build_tree(events)
    loops = [n for n in tree.nodes if n.node_type == "loop"]
    assert len(loops) == 1, "expected exactly one loop node"
    lp = loops[0]

    # item_count must be K=3 (items per host), NOT H*K=6 (total item results)
    assert lp.item_count == 3, f"item_count should be 3 (per-host), got {lp.item_count}"

    # Each host must have item_index values {0, 1, 2}
    item_results = [r for r in tree.results if r.node_id == lp.node_id and r.item_index is not None]
    for host in ("h1", "h2"):
        host_indices = {r.item_index for r in item_results if r.host == host}
        assert host_indices == {0, 1, 2}, \
            f"host {host!r} item_indices should be {{0,1,2}}, got {host_indices}"


def test_durations_present_for_terminal_tasks_745():
    tree = build_tree(_events("job_745_events.json"))
    ran = [n for n in tree.nodes if n.node_type in ("task", "loop")
           and any(r.node_id == n.node_id for r in tree.results)]
    assert ran
    assert all(n.duration_s is None or n.duration_s >= 0 for n in ran)
    # Tightened: at least one task node must actually carry a non-None duration_s and started_at
    assert any(n.duration_s is not None for n in ran), \
        "expected at least one task node with a populated duration_s"
    assert any(n.started_at is not None for n in ran), \
        "expected at least one task node with a populated started_at"
