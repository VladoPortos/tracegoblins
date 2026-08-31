"""
B5 — Golden assertions for parse_job_events on REAL Day2Actions AWX fixtures.

Fixtures captured from live AWX 24.6.1 in M4 Task B4:
  - job_745_events.json  failed job  (runner_on_failed assertion)
  - job_743_events.json  successful job (multi-host, items, warning)

Real-vs-synthetic drift fixed in job_events.py:
  Real AWX top-level "host" field is an integer DB record ID, NOT the hostname
  string.  The actual hostname lives in event_data.host / event_data.remote_addr.
  _host() was updated to prefer event_data.host first and only fall back to the
  top-level field when it is already a str (for synthetic fixtures and future
  compatibility).
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.logparser import parse_job_events

FIXTURE_DIR = Path(__file__).parent.parent / "fixtures" / "awx"


@pytest.fixture(scope="module")
def events_745() -> list[dict]:
    return json.loads((FIXTURE_DIR / "job_745_events.json").read_text())


@pytest.fixture(scope="module")
def events_743() -> list[dict]:
    return json.loads((FIXTURE_DIR / "job_743_events.json").read_text())


# ── Job 745 (FAILED) ──────────────────────────────────────────────────────────

class TestJob745Failed:
    """Golden assertions for the failed Day2Actions job 745."""

    def test_play_tree(self, events_745):
        run = parse_job_events(events_745)
        assert len(run.plays) == 1
        assert run.plays[0].name == "Day2Actions entrypoint"
        assert run.task_count == 31

    def test_all_host_keys_are_strings(self, events_745):
        """Real AWX top-level host field is int; adapter must return str hostname."""
        run = parse_job_events(events_745)
        bad = [
            (t.name, h)
            for p in run.plays
            for t in p.tasks
            for h in t.statuses
            if not isinstance(h, str)
        ]
        assert bad == [], f"Non-string host keys found: {bad}"

    def test_failed_task_detail(self, events_745):
        run = parse_job_events(events_745)
        failed_tasks = [
            t
            for p in run.plays
            for t in p.tasks
            if "failed" in t.statuses.values()
        ]
        assert len(failed_tasks) == 1
        ft = failed_tasks[0]
        assert ft.name == "Ensure target VM exists"
        assert ft.statuses == {"localhost": "failed"}
        # failure detail captured from event_data.res.msg
        assert ft.error is not None
        err_blob = json.loads(ft.error)
        assert "not found in CDB" in err_blob.get("msg", "")

    def test_durations_from_created_deltas(self, events_745):
        """Tasks with a terminal runner event must have a float duration_s > 0."""
        run = parse_job_events(events_745)
        tasks_with_runner = [
            t
            for p in run.plays
            for t in p.tasks
            if t.statuses and "included" not in t.statuses.values()
        ]
        assert tasks_with_runner, "Expected tasks with runner events"
        bad = [t.name for t in tasks_with_runner if t.duration_s is None or t.duration_s < 0]
        assert bad == [], f"Tasks missing positive duration: {bad}"

    def test_include_tasks_have_no_duration(self, events_745):
        """playbook_on_include tasks have no terminal event → duration_s is None."""
        run = parse_job_events(events_745)
        include_tasks = [
            t
            for p in run.plays
            for t in p.tasks
            if t.statuses == {"localhost": "included"}
        ]
        assert include_tasks, "Expected at least one included task"
        assert all(t.duration_s is None for t in include_tasks)

    def test_recap_from_playbook_on_stats(self, events_745):
        run = parse_job_events(events_745)
        recap = {r.host: r for r in run.recap}
        assert set(recap) == {"localhost"}
        lh = recap["localhost"]
        assert lh.ok == 11
        assert lh.failed == 1
        assert lh.changed == 0
        assert lh.unreachable == 0
        assert lh.skipped == 15

    def test_verbose_events_ignored(self, events_745):
        """verbose events must not create plays/tasks or inflate warnings."""
        run = parse_job_events(events_745)
        # warnings come from Ansible "warning" events, not "verbose"
        assert run.warnings == 0


# ── Job 743 (SUCCESSFUL) ─────────────────────────────────────────────────────

class TestJob743Successful:
    """Golden assertions for the successful Day2Actions job 743."""

    def test_play_tree(self, events_743):
        run = parse_job_events(events_743)
        assert len(run.plays) == 3
        assert run.plays[0].name == "Day2Actions entrypoint"
        assert run.plays[1].name == "Day2Actions process managed options"
        assert run.plays[2].name == "Cleanup temporary SSH key files"
        assert run.task_count == 284

    def test_all_host_keys_are_strings(self, events_743):
        run = parse_job_events(events_743)
        bad = [
            (t.name, h)
            for p in run.plays
            for t in p.tasks
            for h in t.statuses
            if not isinstance(h, str)
        ]
        assert bad == [], f"Non-string host keys found: {bad}"

    def test_no_failures(self, events_743):
        run = parse_job_events(events_743)
        failed = [
            t
            for p in run.plays
            for t in p.tasks
            if "failed" in t.statuses.values()
        ]
        assert failed == []

    def test_warning_counted(self, events_743):
        """Job 743 has one Ansible warning event."""
        run = parse_job_events(events_743)
        assert run.warnings == 1

    def test_recap_multi_host(self, events_743):
        run = parse_job_events(events_743)
        recap = {r.host: r for r in run.recap}
        assert set(recap) == {"localhost", "d2a-throwaway-del"}
        lh = recap["localhost"]
        assert lh.ok == 101
        assert lh.changed == 2
        assert lh.failed == 0
        assert lh.skipped == 67
        vm = recap["d2a-throwaway-del"]
        assert vm.ok == 72
        assert vm.changed == 5
        assert vm.failed == 0
        assert vm.skipped == 19

    def test_item_tasks_counted(self, events_743):
        """Job 743 contains runner_item_on_ok events → some tasks have items > 0."""
        run = parse_job_events(events_743)
        tasks_with_items = [
            t
            for p in run.plays
            for t in p.tasks
            if t.items > 0
        ]
        assert tasks_with_items, "Expected at least one task with loop items"
