"""Canned AWX 24.6.1 payloads for the in-Docker mock-AWX E2E server (Task G2).

Pure data + tiny helpers (no DB/HTTP). Three Day2Actions jobs in org DXC (id 2):
743/744 successful, 745 failed (runner_on_failed with event_data.res.msg). `created`
stamps are spaced by whole seconds so the M2 job_events adapter yields exact, non-zero
durations — the E2E asserts a rendered duration on the Status Map.
"""
from __future__ import annotations

from typing import Any

ORG = {"id": 2, "name": "DXC"}
TEMPLATE = {"id": 20, "name": "Day2Actions"}
CREATED_BY = {"id": 1, "username": "cloudauto"}


def job_summary_shape(job_id: int) -> dict[str, Any]:
    """One AWX `job` object exactly as GET /api/v2/jobs/{id}/ returns it."""
    status = "failed" if job_id == 745 else "successful"
    # whole-minute offsets per job so finished timestamps are distinct + ordered
    hh = 10 + (job_id - 743)
    return {
        "id": job_id,
        "type": "job",
        "name": "Day2Actions",
        "status": status,
        "failed": status == "failed",
        "created": f"2026-06-04T{hh:02d}:00:00.000000Z",
        "started": f"2026-06-04T{hh:02d}:00:01.000000Z",
        "finished": f"2026-06-04T{hh:02d}:00:20.000000Z",
        "elapsed": 19.0,
        "playbook": "main.yaml",
        "launch_type": "manual",
        "organization": 2,
        "job_template": 20,
        "url": f"/api/v2/jobs/{job_id}/",
        "summary_fields": {
            "organization": dict(ORG),
            "job_template": dict(TEMPLATE),
            "created_by": dict(CREATED_BY),
        },
        "related": {
            "job_events": f"/api/v2/jobs/{job_id}/job_events/",
            "stdout": f"/api/v2/jobs/{job_id}/stdout/",
        },
    }


MOCK_JOBS: list[dict[str, Any]] = [job_summary_shape(i) for i in (743, 744, 745)]


def _ok_events(job_id: int) -> list[dict[str, Any]]:
    """Simple 2-task successful job. Job 743 is extended with an include + loop so the
    synced tree exercises containers and the stepper in the Path Explorer E2E."""
    hh = 10 + (job_id - 743)
    base = [
        {"event": "playbook_on_start", "counter": 1,
         "created": f"2026-06-04T{hh:02d}:00:01.000000Z",
         "stdout": "", "event_data": {"playbook": "main.yaml"}},
        {"event": "playbook_on_play_start", "counter": 2,
         "created": f"2026-06-04T{hh:02d}:00:02.000000Z",
         "stdout": "\r\nPLAY [Day2Actions] *****\r\n",
         "event_data": {"play": "Day2Actions", "play_uuid": "p1"}},
        {"event": "playbook_on_task_start", "counter": 3,
         "created": f"2026-06-04T{hh:02d}:00:03.000000Z",
         "stdout": "\r\nTASK [Gathering Facts] *****\r\n",
         "event_data": {"play": "Day2Actions", "task": "Gathering Facts", "task_uuid": "t1"}},
        {"event": "runner_on_ok", "counter": 4,
         "created": f"2026-06-04T{hh:02d}:00:06.000000Z", "host": "host-a",
         "stdout": "ok: [host-a]\r\n",
         "event_data": {"task": "Gathering Facts", "task_uuid": "t1", "host": "host-a",
                        "res": {"changed": False, "msg": "facts ok"}}},
        {"event": "playbook_on_task_start", "counter": 5,
         "created": f"2026-06-04T{hh:02d}:00:07.000000Z",
         "stdout": "\r\nTASK [Apply day-2 config] *****\r\n",
         "event_data": {"play": "Day2Actions", "task": "Apply day-2 config", "task_uuid": "t2"}},
        {"event": "runner_on_ok", "counter": 6,
         "created": f"2026-06-04T{hh:02d}:00:11.000000Z", "host": "host-a",
         "stdout": "changed: [host-a]\r\n",
         "event_data": {"task": "Apply day-2 config", "task_uuid": "t2", "host": "host-a",
                        "res": {"changed": True, "msg": "config applied"}}},
        {"event": "playbook_on_stats", "counter": 7,
         "created": f"2026-06-04T{hh:02d}:00:12.000000Z",
         "stdout": "\r\nPLAY RECAP *****\r\nhost-a : ok=2 changed=1 unreachable=0 failed=0\r\n",
         "event_data": {"ok": {"host-a": 2}, "changed": {"host-a": 1},
                        "failures": {}, "dark": {}, "skipped": {}, "ignored": {}}},
    ]
    if job_id != 743:
        return base

    # Extend job 743 with an include container + a 3-item loop so the Path Explorer
    # e2e can assert non-trivial tree structure (containers + stepper).
    include_extras: list[dict[str, Any]] = [
        # playbook_on_include pushes "packages.yml" onto the include stack
        {"event": "playbook_on_include", "counter": 8,
         "created": f"2026-06-04T{hh:02d}:00:13.000000Z",
         "stdout": "",
         "event_data": {"play": "Day2Actions", "play_uuid": "p1",
                        "included_file": "/runner/project/tasks/packages.yml"}},
        # task under the include (task_path matches packages.yml)
        {"event": "playbook_on_task_start", "counter": 9,
         "created": f"2026-06-04T{hh:02d}:00:14.000000Z",
         "stdout": "\r\nTASK [Install packages] *****\r\n",
         "event_data": {"play": "Day2Actions", "task": "Install packages",
                        "task_uuid": "t3",
                        "task_path": "/runner/project/tasks/packages.yml:4"}},
        # 3 item results for the loop
        {"event": "runner_item_on_ok", "counter": 10,
         "created": f"2026-06-04T{hh:02d}:00:15.000000Z", "host": "host-a",
         "stdout": "ok: [host-a] => (item=nginx)\r\n",
         "event_data": {"task": "Install packages", "task_uuid": "t3", "host": "host-a",
                        "res": {"changed": False, "item": "nginx"}}},
        {"event": "runner_item_on_ok", "counter": 11,
         "created": f"2026-06-04T{hh:02d}:00:16.000000Z", "host": "host-a",
         "stdout": "changed: [host-a] => (item=curl)\r\n",
         "event_data": {"task": "Install packages", "task_uuid": "t3", "host": "host-a",
                        "res": {"changed": True, "item": "curl"}}},
        {"event": "runner_item_on_ok", "counter": 12,
         "created": f"2026-06-04T{hh:02d}:00:17.000000Z", "host": "host-a",
         "stdout": "changed: [host-a] => (item=git)\r\n",
         "event_data": {"task": "Install packages", "task_uuid": "t3", "host": "host-a",
                        "res": {"changed": True, "item": "git"}}},
        # terminal runner_on_ok closing the loop task
        {"event": "runner_on_ok", "counter": 13,
         "created": f"2026-06-04T{hh:02d}:00:18.000000Z", "host": "host-a",
         "stdout": "ok: [host-a]\r\n",
         "event_data": {"task": "Install packages", "task_uuid": "t3", "host": "host-a",
                        "res": {"changed": True}}},
    ]
    return base + include_extras


def _failed_events() -> list[dict[str, Any]]:
    hh = 12
    return [
        {"event": "playbook_on_start", "counter": 1,
         "created": f"2026-06-04T{hh:02d}:00:01.000000Z",
         "stdout": "", "event_data": {"playbook": "main.yaml"}},
        {"event": "playbook_on_play_start", "counter": 2,
         "created": f"2026-06-04T{hh:02d}:00:02.000000Z",
         "stdout": "\r\nPLAY [Day2Actions] *****\r\n",
         "event_data": {"play": "Day2Actions", "play_uuid": "p1"}},
        {"event": "playbook_on_task_start", "counter": 3,
         "created": f"2026-06-04T{hh:02d}:00:03.000000Z",
         "stdout": "\r\nTASK [Gathering Facts] *****\r\n",
         "event_data": {"play": "Day2Actions", "task": "Gathering Facts", "task_uuid": "t1"}},
        {"event": "runner_on_ok", "counter": 4,
         "created": f"2026-06-04T{hh:02d}:00:06.000000Z", "host": "host-b",
         "stdout": "ok: [host-b]\r\n",
         "event_data": {"task": "Gathering Facts", "task_uuid": "t1", "host": "host-b",
                        "res": {"changed": False, "msg": "facts ok"}}},
        {"event": "playbook_on_task_start", "counter": 5,
         "created": f"2026-06-04T{hh:02d}:00:07.000000Z",
         "stdout": "\r\nTASK [Assert day-2 preconditions] *****\r\n",
         "event_data": {"play": "Day2Actions", "task": "Assert day-2 preconditions",
                        "task_uuid": "t2"}},
        {"event": "runner_on_failed", "counter": 6,
         "created": f"2026-06-04T{hh:02d}:00:13.000000Z", "host": "host-b",
         "stdout": "fatal: [host-b]: FAILED! => {\"msg\": \"Assertion failed\"}\r\n",
         "event_data": {"task": "Assert day-2 preconditions", "task_uuid": "t2", "host": "host-b",
                        "play": "Day2Actions",
                        "res": {"changed": False, "failed": True,
                                "msg": "Day-2 precondition not met on host-b: disk_free < 10G",
                                "assertion": "disk_free >= 10G"}}},
        {"event": "playbook_on_stats", "counter": 7,
         "created": f"2026-06-04T{hh:02d}:00:14.000000Z",
         "stdout": "\r\nPLAY RECAP *****\r\nhost-b : ok=1 changed=0 unreachable=0 failed=1\r\n",
         "event_data": {"ok": {"host-b": 1}, "changed": {},
                        "failures": {"host-b": 1}, "dark": {}, "skipped": {}, "ignored": {}}},
    ]


MOCK_JOB_EVENTS: dict[int, list[dict[str, Any]]] = {
    743: _ok_events(743),
    744: _ok_events(744),
    745: _failed_events(),
}


def _job_detail_shape(job_id: int) -> dict[str, Any]:
    """AWX GET /api/v2/jobs/{id}/ payload (subset consumed by get_job_detail / _to_job_detail)."""
    status = "failed" if job_id == 745 else "successful"
    hh = 10 + (job_id - 743)
    return {
        "id": job_id,
        "type": "job",
        "status": status,
        "extra_vars": '{"target_env": "staging", "deploy_version": "2.3.1"}',
        "limit": "host-a,host-b",
        "scm_revision": "abc1234def567",
        "started": f"2026-06-04T{hh:02d}:00:01.000000Z",
        "finished": f"2026-06-04T{hh:02d}:00:20.000000Z",
        "elapsed": 19.0,
        "playbook": "main.yaml",
        "summary_fields": {
            "project": {"id": 10, "name": "Day2Actions"},
            "job_template": {"id": 20, "name": "Day2Actions"},
            "organization": dict(ORG),
            "created_by": dict(CREATED_BY),
        },
    }


MOCK_JOB_DETAILS: dict[int, dict[str, Any]] = {i: _job_detail_shape(i) for i in (743, 744, 745)}

# ---------------------------------------------------------------------------
# Projects (Task 14)  — id MUST match the "project" id in MOCK_JOB_DETAILS
# so that the auto-link wires synced runs to this project (project id 10).
# ---------------------------------------------------------------------------
PROJECTS: list[dict[str, Any]] = [
    {
        "id": 10,
        "name": "Day2Actions",
        "scm_type": "git",
        "scm_url": "https://github.com/example/day2actions.git",
        "scm_branch": "main",
        "scm_revision": "abc1234def567",
        "summary_fields": {
            "organization": dict(ORG),
        },
    }
]


def paginate(items: list[dict[str, Any]], *, base: str, page: int, page_size: int,
             query: str = "") -> dict[str, Any]:
    """Return a DRF-style paginated page: {count, next, previous, results}.
    `next`/`previous` are relative URLs (the client follows both absolute + relative)."""
    start = (page - 1) * page_size
    chunk = items[start:start + page_size]
    sep = "&" if query else ""
    has_next = start + page_size < len(items)
    has_prev = page > 1
    nxt = f"{base}?{query}{sep}page={page + 1}&page_size={page_size}" if has_next else None
    prev = f"{base}?{query}{sep}page={page - 1}&page_size={page_size}" if has_prev else None
    return {"count": len(items), "next": nxt, "previous": prev, "results": chunk}
