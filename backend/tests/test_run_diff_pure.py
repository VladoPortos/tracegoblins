"""Pure unit tests for run_diff.diff_tasks (no DB — the function is pure by design).

Covers the host-status classification edge cases that the DB-backed endpoint tests
in test_run_diff.py do not exercise (notably failed -> skipped/included).
"""
from __future__ import annotations

from types import SimpleNamespace

from app.services.run_diff import diff_tasks


def _t(seq, name, hosts, *, play="Play 1", duration=None):
    return SimpleNamespace(play_name=play, name=name, hosts=hosts, seq=seq, duration_s=duration)


def test_failed_host_going_skipped_is_not_reported_as_fixed():
    # A host that was failing and is now *skipped* did not pass — it stopped running.
    base = [_t(1, "Deploy", {"h1": "failed"})]
    cur = [_t(1, "Deploy", {"h1": "skipped"})]
    out = diff_tasks(cur, base)
    assert out["fixed"] == []
    assert out["still_failing"] == []
    assert out["newly_failing"] == []
    # Host present in both runs -> neither added nor removed.
    assert out["added_count"] == 0 and out["removed_count"] == 0


def test_unreachable_host_going_included_is_not_reported_as_fixed():
    base = [_t(1, "Deploy", {"h1": "unreachable"})]
    cur = [_t(1, "Deploy", {"h1": "included"})]
    out = diff_tasks(cur, base)
    assert out["fixed"] == []
    assert out["still_failing"] == []
    assert out["newly_failing"] == []


def test_failed_host_going_ok_is_a_real_fix():
    base = [_t(1, "Deploy", {"h1": "failed"})]
    cur = [_t(1, "Deploy", {"h1": "ok"})]
    out = diff_tasks(cur, base)
    assert [(e.task_name, e.before, e.after) for e in out["fixed"]] == [("Deploy", "failed", "ok")]


def test_failed_host_going_changed_is_a_real_fix():
    # 'changed' means the task ran and made a change — a genuine recovery from failure.
    base = [_t(1, "Deploy", {"h1": "failed"})]
    cur = [_t(1, "Deploy", {"h1": "changed"})]
    out = diff_tasks(cur, base)
    assert [(e.task_name, e.after) for e in out["fixed"]] == [("Deploy", "changed")]


def test_emitted_entries_carry_current_run_seq():
    # Guards the dead-branch removal (F6): every emitted entry has a current-run seq.
    base = [_t(1, "A", {"h1": "ok"})]
    cur = [_t(7, "A", {"h1": "failed"})]
    out = diff_tasks(cur, base)
    assert [e.seq for e in out["newly_failing"]] == [7]


def test_same_task_multi_host_order_is_deterministic_by_host():
    # One task failing on several hosts: all entries share (group, seq), so without a host
    # tiebreaker their order is set-iteration (hash) order. Lock it to alphabetical host order.
    base = [_t(1, "Deploy", {"h1": "ok", "h2": "ok", "h3": "ok", "h4": "ok"})]
    cur = [_t(1, "Deploy", {"h3": "failed", "h1": "failed", "h4": "failed", "h2": "failed"})]
    out = diff_tasks(cur, base)
    assert [e.host for e in out["newly_failing"]] == ["h1", "h2", "h3", "h4"]
