from tests.e2e.mock_awx_data import (
    MOCK_JOBS,
    MOCK_JOB_EVENTS,
    job_summary_shape,
    paginate,
)


def test_three_jobs_one_failed_in_dxc_org():
    assert [j["id"] for j in MOCK_JOBS] == [743, 744, 745]
    assert {j["status"] for j in MOCK_JOBS} == {"successful", "failed"}
    failed = [j for j in MOCK_JOBS if j["status"] == "failed"]
    assert [j["id"] for j in failed] == [745]
    for j in MOCK_JOBS:
        assert j["summary_fields"]["organization"] == {"id": 2, "name": "DXC"}
        assert j["summary_fields"]["job_template"]["name"] == "Day2Actions"
        assert j["type"] == "job"
        assert j["url"].startswith("/api/v2/jobs/")


def test_job_shape_has_every_field_the_client_maps():
    j = job_summary_shape(745)
    for key in ("id", "name", "status", "created", "started", "finished",
                "elapsed", "playbook", "launch_type", "organization", "url"):
        assert key in j
    sf = j["summary_fields"]
    assert sf["organization"]["name"] == "DXC"
    assert sf["job_template"]["name"] == "Day2Actions"
    assert sf["created_by"]["username"] == "cloudauto"


def test_failed_job_745_events_carry_runner_on_failed_with_msg():
    events = MOCK_JOB_EVENTS[745]
    types = [e["event"] for e in events]
    assert "playbook_on_stats" in types
    failed = [e for e in events if e["event"] == "runner_on_failed"]
    assert failed, "job 745 must have a runner_on_failed event"
    assert failed[0]["event_data"]["res"]["msg"]
    # adapter needs whole-second created deltas -> non-zero durations
    starts = [e for e in events if e["event"] == "playbook_on_task_start"]
    assert len(starts) >= 1


def test_paginate_yields_next_links_and_full_count():
    page1 = paginate(MOCK_JOBS, base="/api/v2/jobs/", page=1, page_size=2)
    assert page1["count"] == 3
    assert page1["next"] is not None and "page=2" in page1["next"]
    assert len(page1["results"]) == 2
    page2 = paginate(MOCK_JOBS, base="/api/v2/jobs/", page=2, page_size=2)
    assert page2["next"] is None
    assert len(page2["results"]) == 1
