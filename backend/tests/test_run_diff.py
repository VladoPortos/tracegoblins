from __future__ import annotations

import uuid
from datetime import timedelta

from app.core.clock import utcnow
from app.models import Run, Task


def _run(user, *, status, template="Deploy App", when, elapsed=None, team_id=None, recap=None):
    return Run(
        owner_user_id=user.id, team_id=team_id, status=status,
        template_name=template, launched_at=when, elapsed=elapsed, recap=recap or [],
    )


def _task(run, seq, *, play="Play 1", name="Task", status="ok", hosts=None, duration=None):
    return Task(
        run_id=run.id, seq=seq, play_name=play, name=name, status=status,
        hosts=hosts or {}, duration_s=duration,
    )


async def _diff(c, run):
    r = await c.get(f"/api/runs/{run.id}/diff")
    assert r.status_code == 200
    return r.json()


# ---------------------------------------------------------------------------
# Baseline selection
# ---------------------------------------------------------------------------

async def test_baseline_latest_older_green_wins(db, make_user, session_for):
    user = await make_user(email="diff1@example.com")
    other = await make_user(email="diff1-other@example.com")
    c = await session_for(user)
    now = utcnow()

    older_green = _run(user, status="ok", when=now - timedelta(hours=3))
    latest_older_green = _run(user, status="changed", when=now - timedelta(hours=2))
    other_template_green = _run(user, status="ok", template="Other Tmpl",
                                when=now - timedelta(hours=1))
    # Another user's PERSONAL green run, more recent than latest_older_green but
    # still older than R — must NOT be chosen (visibility!).
    invisible_green = _run(other, status="ok", when=now - timedelta(minutes=30))
    current = _run(user, status="failed", when=now)
    newer_green = _run(user, status="ok", when=now + timedelta(hours=1))
    db.add_all([older_green, latest_older_green, other_template_green,
                invisible_green, current, newer_green])
    await db.flush()

    body = await _diff(c, current)
    assert body["baseline"] is not None
    assert body["baseline"]["id"] == str(latest_older_green.id)
    assert body["reason"] is None


async def test_baseline_tiebreak_prefers_more_recently_created(db, make_user, session_for):
    # Two green baselines share the SAME effective timestamp. The more recently ingested
    # one (created_at) must win deterministically — NOT the lower random UUID. Give the
    # earlier-created run the SMALLER uuid so an id.asc()-only tiebreak would pick the wrong one.
    user = await make_user(email="diff-tie@example.com")
    c = await session_for(user)
    now = utcnow()
    same_when = now - timedelta(hours=1)
    old_created = Run(
        id=uuid.UUID(int=1), owner_user_id=user.id, status="ok", template_name="Deploy App",
        launched_at=same_when, created_at=now - timedelta(minutes=20),
    )
    new_created = Run(
        id=uuid.UUID(int=2), owner_user_id=user.id, status="changed", template_name="Deploy App",
        launched_at=same_when, created_at=now - timedelta(minutes=5),
    )
    current = _run(user, status="failed", when=now)
    db.add_all([old_created, new_created, current])
    await db.flush()

    body = await _diff(c, current)
    assert body["baseline"] is not None
    assert body["baseline"]["id"] == str(new_created.id)


async def test_reason_no_template(db, make_user, session_for):
    user = await make_user(email="diff2@example.com")
    c = await session_for(user)
    run = _run(user, status="failed", template=None, when=utcnow())
    # A green older run exists, but R has no template -> no baseline regardless.
    db.add_all([run, _run(user, status="ok", when=utcnow() - timedelta(hours=1))])
    await db.flush()

    body = await _diff(c, run)
    assert body["baseline"] is None
    assert body["reason"] == "no_template"


async def test_reason_no_green_run(db, make_user, session_for):
    user = await make_user(email="diff3@example.com")
    c = await session_for(user)
    now = utcnow()
    current = _run(user, status="failed", when=now)
    db.add_all([
        current,
        _run(user, status="failed", when=now - timedelta(hours=2)),  # older but not green
        _run(user, status="ok", when=now + timedelta(hours=1)),      # green but NEWER
    ])
    await db.flush()

    body = await _diff(c, current)
    assert body["baseline"] is None
    assert body["reason"] == "no_green_run"


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------

async def test_newly_failing_classification(db, make_user, session_for):
    user = await make_user(email="diff4@example.com")
    c = await session_for(user)
    now = utcnow()
    base = _run(user, status="ok", when=now - timedelta(hours=1))
    cur = _run(user, status="failed", when=now)
    db.add_all([base, cur])
    await db.flush()
    db.add_all([
        _task(base, 1, name="A", hosts={"h1": "ok"}),
        _task(base, 2, name="B", hosts={"h1": "ok"}),
        _task(cur, 1, name="A", status="failed", hosts={"h1": "failed"}),
        _task(cur, 2, name="B", hosts={"h1": "ok"}),
        _task(cur, 3, name="C", status="failed", hosts={"h2": "failed"}),
    ])
    await db.flush()

    body = await _diff(c, cur)
    got = {(e["task_name"], e["host"]) for e in body["newly_failing"]}
    assert got == {("A", "h1"), ("C", "h2")}
    by_name = {e["task_name"]: e for e in body["newly_failing"]}
    assert by_name["A"]["before"] == "ok" and by_name["A"]["after"] == "failed"
    assert by_name["C"]["before"] is None and by_name["C"]["after"] == "failed"
    assert by_name["A"]["seq"] == 1 and by_name["C"]["seq"] == 3
    assert body["fixed"] == []
    assert body["still_failing"] == []


async def test_fixed_and_still_failing(db, make_user, session_for):
    user = await make_user(email="diff5@example.com")
    c = await session_for(user)
    now = utcnow()
    base = _run(user, status="changed", when=now - timedelta(hours=1))
    cur = _run(user, status="failed", when=now)
    db.add_all([base, cur])
    await db.flush()
    db.add_all([
        _task(base, 1, name="A", status="failed", hosts={"h1": "failed"}),
        _task(base, 2, name="B", status="failed", hosts={"h1": "unreachable"}),
        _task(cur, 1, name="A", hosts={"h1": "ok"}),
        _task(cur, 2, name="B", status="failed", hosts={"h1": "failed"}),
    ])
    await db.flush()

    body = await _diff(c, cur)
    assert [(e["task_name"], e["host"], e["before"], e["after"]) for e in body["fixed"]] == \
        [("A", "h1", "failed", "ok")]
    assert [(e["task_name"], e["host"], e["before"], e["after"]) for e in body["still_failing"]] == \
        [("B", "h1", "unreachable", "failed")]
    assert body["newly_failing"] == []


async def test_failed_host_skipped_now_not_listed_as_fixed(db, make_user, session_for):
    # End-to-end guard for the host-status gate: failed -> skipped is not a fix.
    user = await make_user(email="diff-skip@example.com")
    c = await session_for(user)
    now = utcnow()
    base = _run(user, status="failed", when=now - timedelta(hours=1))
    cur = _run(user, status="ok", when=now)
    db.add_all([base, cur])
    await db.flush()
    db.add_all([
        _task(base, 1, name="Maybe", status="failed", hosts={"h1": "failed"}),
        _task(cur, 1, name="Maybe", status="skipped", hosts={"h1": "skipped"}),
    ])
    await db.flush()

    body = await _diff(c, cur)
    assert body["fixed"] == []
    assert body["still_failing"] == [] and body["newly_failing"] == []


async def test_added_and_removed_counts(db, make_user, session_for):
    user = await make_user(email="diff6@example.com")
    c = await session_for(user)
    now = utcnow()
    base = _run(user, status="ok", when=now - timedelta(hours=1))
    cur = _run(user, status="ok", when=now)
    db.add_all([base, cur])
    await db.flush()
    db.add_all([
        _task(base, 1, name="Common", hosts={"h1": "ok"}),
        _task(base, 2, name="Gone", hosts={"h1": "ok"}),       # removed (non-failing)
        _task(base, 3, name="GoneFail", status="failed",
              hosts={"h1": "failed"}),                          # removed (was FAILING)
        _task(cur, 1, name="Common", hosts={"h1": "ok"}),
        _task(cur, 2, name="New", hosts={"h1": "changed"}),    # added (non-failing)
    ])
    await db.flush()

    body = await _diff(c, cur)
    assert body["added_count"] == 1
    # removed_count = baseline rows absent now, ANY status (incl. failing-before).
    assert body["removed_count"] == 2
    assert body["newly_failing"] == [] and body["fixed"] == [] and body["still_failing"] == []


async def test_duplicate_task_names_use_occurrence_index(db, make_user, session_for):
    user = await make_user(email="diff7@example.com")
    c = await session_for(user)
    now = utcnow()
    base = _run(user, status="ok", when=now - timedelta(hours=1))
    cur = _run(user, status="failed", when=now)
    db.add_all([base, cur])
    await db.flush()
    # Two tasks with the SAME (play, name); only the second occurrence regressed.
    db.add_all([
        _task(base, 1, name="Dup", hosts={"h1": "ok"}),
        _task(base, 2, name="Dup", hosts={"h1": "ok"}),
        _task(cur, 1, name="Dup", hosts={"h1": "ok"}),
        _task(cur, 5, name="Dup", status="failed", hosts={"h1": "failed"}),
    ])
    await db.flush()

    body = await _diff(c, cur)
    assert len(body["newly_failing"]) == 1
    entry = body["newly_failing"][0]
    assert entry["task_name"] == "Dup" and entry["host"] == "h1"
    assert entry["before"] == "ok" and entry["after"] == "failed"
    assert entry["seq"] == 5  # CURRENT-run seq of the second occurrence
    assert body["still_failing"] == [] and body["fixed"] == []


async def test_hosts_newly_unreachable_from_recap(db, make_user, session_for):
    user = await make_user(email="diff8@example.com")
    c = await session_for(user)
    now = utcnow()
    base = _run(user, status="ok", when=now - timedelta(hours=1),
                recap=[{"host": "h1", "ok": 3, "unreachable": 0}])
    cur = _run(user, status="failed", when=now, recap=[
        {"host": "h1", "ok": 1, "unreachable": 1},   # 0 -> 1: newly unreachable
        {"host": "h2", "unreachable": 2},            # absent before: newly unreachable
        {"host": "h3", "ok": 4, "unreachable": 0},   # fine now: not listed
    ])
    db.add_all([base, cur])
    await db.flush()

    body = await _diff(c, cur)
    assert sorted(body["hosts_newly_unreachable"]) == ["h1", "h2"]


async def test_duration_deltas(db, make_user, session_for):
    user = await make_user(email="diff9@example.com")
    c = await session_for(user)
    now = utcnow()
    base = _run(user, status="ok", when=now - timedelta(hours=1), elapsed=60.0)
    cur = _run(user, status="ok", when=now, elapsed=100.0)
    db.add_all([base, cur])
    await db.flush()
    db.add_all([
        _task(base, 1, name="Slow", hosts={"h1": "ok"}, duration=10.0),
        _task(base, 2, name="Steady", hosts={"h1": "ok"}, duration=10.0),
        _task(base, 3, name="NoDur", hosts={"h1": "ok"}, duration=None),
        _task(cur, 1, name="Slow", hosts={"h1": "ok"}, duration=40.0),    # +30 -> listed
        _task(cur, 2, name="Steady", hosts={"h1": "ok"}, duration=12.0),  # +2 < 5s -> not listed
        _task(cur, 3, name="NoDur", hosts={"h1": "ok"}, duration=25.0),   # baseline NULL -> skipped
    ])
    await db.flush()

    body = await _diff(c, cur)
    assert body["duration_delta_s"] == 40.0  # 100 - 60
    assert len(body["slowest_changes"]) == 1
    sc = body["slowest_changes"][0]
    assert sc["task_name"] == "Slow" and sc["seq"] == 1
    assert sc["before_s"] == 10.0 and sc["after_s"] == 40.0 and sc["delta_s"] == 30.0


# ---------------------------------------------------------------------------
# Route auth/visibility
# ---------------------------------------------------------------------------

async def test_diff_invisible_run_404(db, make_user, session_for):
    owner = await make_user(email="diff10-owner@example.com")
    viewer = await make_user(email="diff10-viewer@example.com")
    run = _run(owner, status="failed", when=utcnow())  # personal upload, not shared
    db.add(run)
    await db.flush()
    c = await session_for(viewer)

    r = await c.get(f"/api/runs/{run.id}/diff")
    assert r.status_code == 404
    r = await c.get(f"/api/runs/{uuid.uuid4()}/diff")
    assert r.status_code == 404
