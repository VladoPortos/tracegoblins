from app.logparser import parse_job_events
from tests.fixtures.job_events_sample import SAMPLE_JOB_EVENTS


def test_tree_shape():
    run = parse_job_events(SAMPLE_JOB_EVENTS)
    assert run.task_count == 3 and len(run.plays) == 1
    assert run.plays[0].name == "Configure web tier"
    assert [t.name for t in run.plays[0].tasks] == ["Install nginx", "Deploy vhosts", "Restart nginx"]


def test_statuses_items_error():
    t1, t2, t3 = parse_job_events(SAMPLE_JOB_EVENTS).plays[0].tasks
    assert t1.statuses == {"web01": "ok"} and t1.full == "webserver : Install nginx"
    assert t2.statuses == {"web01": "changed"} and t2.items == 3
    assert t3.statuses == {"web02": "unreachable"}
    assert t3.error is not None and "No route to host" in t3.error
    assert t1.error is None


def test_recap_remaps_dark_and_failures():
    recap = {r.host: r for r in parse_job_events(SAMPLE_JOB_EVENTS).recap}
    assert set(recap) == {"web01", "web02"}
    assert (recap["web01"].ok, recap["web01"].changed) == (2, 1)
    assert recap["web02"].unreachable == 1 and recap["web02"].failed == 0


def test_durations_from_created_deltas():
    t1, t2, t3 = parse_job_events(SAMPLE_JOB_EVENTS).plays[0].tasks
    assert (t1.duration_s, t2.duration_s, t3.duration_s) == (2.0, 3.0, 1.0)


def test_malformed_events_do_not_raise():
    run = parse_job_events([{"event": None}, {}, {"foo": "bar"}, {"event": "verbose"}])
    assert run.task_count == 0 and run.plays == []
