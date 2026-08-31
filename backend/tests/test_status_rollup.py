from app.services.status_rollup import rolled_up_status


def test_container_inherits_worst_descendant_status():
    # play -> include -> failed task; both containers must roll up to failed
    rows = [
        ("play", None, "play", "ok"),
        ("inc", "play", "include", "ok"),
        ("t1", "inc", "task", "failed"),
    ]
    out = rolled_up_status(rows)
    assert out["t1"] == "failed"
    assert out["inc"] == "failed"
    assert out["play"] == "failed"


def test_all_skipped_block_is_skipped_not_ok():
    rows = [
        ("play", None, "play", "ok"),
        ("blk", "play", "block", "ok"),
        ("t1", "blk", "task", "skipped"),
        ("t2", "blk", "task", "skipped"),
    ]
    out = rolled_up_status(rows)
    assert out["blk"] == "skipped"
    assert out["play"] == "skipped"


def test_changed_bubbles_over_ok():
    rows = [
        ("play", None, "play", "ok"),
        ("a", "play", "task", "ok"),
        ("b", "play", "task", "changed"),
    ]
    out = rolled_up_status(rows)
    assert out["play"] == "changed"


def test_leaf_status_unchanged_and_failed_beats_changed():
    rows = [
        ("play", None, "play", "ok"),
        ("a", "play", "task", "changed"),
        ("b", "play", "task", "failed"),
        ("c", "play", "task", "ok"),
    ]
    out = rolled_up_status(rows)
    assert out["a"] == "changed" and out["b"] == "failed" and out["c"] == "ok"
    assert out["play"] == "failed"


def test_unreachable_outranks_failed():
    rows = [
        ("play", None, "play", "ok"),
        ("a", "play", "task", "failed"),
        ("b", "play", "task", "unreachable"),
    ]
    assert rolled_up_status(rows)["play"] == "unreachable"


def test_empty_and_childless_container():
    assert rolled_up_status([]) == {}
    # a container with no children keeps its own status (no crash)
    assert rolled_up_status([("play", None, "play", "ok")]) == {"play": "ok"}


def test_nested_containers_roll_up_through_levels():
    rows = [
        ("pb", None, "playbook", "ok"),
        ("play", "pb", "play", "ok"),
        ("role", "play", "role", "ok"),
        ("t", "role", "task", "failed"),
    ]
    out = rolled_up_status(rows)
    assert out["role"] == "failed" and out["play"] == "failed" and out["pb"] == "failed"
