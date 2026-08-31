from app.logparser.models import HostRecap, ParsedRun, ParsedTask, Play, STATUS_ORDER


def test_status_order_is_prototype_order():
    assert STATUS_ORDER == ["unreachable", "failed", "changed", "ok", "included", "skipped"]


def test_dominant_picks_worst():
    assert ParsedTask(name="a", statuses={"h1": "ok", "h2": "unreachable"}).dominant() == "unreachable"
    assert ParsedTask(name="a", statuses={"h1": "changed", "h2": "ok"}).dominant() == "changed"
    assert ParsedTask(name="a", statuses={"h1": "failed", "h2": "changed"}).dominant() == "failed"
    assert ParsedTask(name="a", statuses={"h1": "included"}).dominant() == "included"
    assert ParsedTask(name="a", statuses={"h1": "skipped", "h2": "ok"}).dominant() == "ok"
    assert ParsedTask(name="a", statuses={}).dominant() == "skipped"


def test_parsedrun_defaults():
    r = ParsedRun()
    assert r.warnings == 0 and r.task_count == 0 and r.plays == [] and r.recap == []
    assert r.meta.template is None and r.meta.job_id is None
    hr = HostRecap(host="h")
    assert (hr.ok, hr.unreachable, hr.ignored) == (0, 0, 0)
    p = Play(name="P")
    assert p.tasks == []
