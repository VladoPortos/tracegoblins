from __future__ import annotations

from datetime import timedelta

from sqlalchemy import select

from app.core.clock import utcnow
from app.models import Run, Team


def _run(user, *, status, template="Deploy App", when, elapsed=None, team_id=None):
    return Run(
        owner_user_id=user.id, team_id=team_id, status=status,
        template_name=template, launched_at=when, elapsed=elapsed,
    )


async def test_single_template_stats(db, make_user, session_for):
    user = await make_user(email="an1@example.com")
    c = await session_for(user)
    now = utcnow()
    ts = [now - timedelta(hours=4 - i) for i in range(4)]  # t0 < t1 < t2 < t3
    statuses = ["ok", "failed", "failed", "ok"]
    elapsed = [10.0, 20.0, None, 30.0]
    runs = [
        _run(user, status=s, when=t, elapsed=e)
        for s, t, e in zip(statuses, ts, elapsed)
    ]
    db.add_all(runs)
    await db.flush()

    r = await c.get("/api/analytics/templates?days=30")
    assert r.status_code == 200
    body = r.json()
    assert body["window_days"] == 30
    assert len(body["items"]) == 1
    it = body["items"][0]
    assert it["template_name"] == "Deploy App"
    assert it["runs"] == 4 and it["failed"] == 2 and it["succeeded"] == 2
    assert it["success_rate"] == 0.5
    assert it["flips"] == 2
    assert it["current_streak"] == 1 and it["streak_kind"] == "pass"
    # first fail at t1, recovered at t3 -> 2 hours
    assert it["time_to_recovery_s"] == (ts[3] - ts[1]).total_seconds()
    assert it["avg_duration_s"] == 20.0
    assert it["last_status"] == "ok"
    assert it["last_run_id"] == str(runs[-1].id)
    assert it["recent"] == statuses
    assert it["recent_ids"] == [str(r_.id) for r_ in runs]
    assert len(it["recent"]) == 4 and len(it["recent_ids"]) == 4


async def test_sorting_worst_first(db, make_user, session_for):
    user = await make_user(email="an2@example.com")
    c = await session_for(user)
    now = utcnow()
    db.add_all([
        _run(user, status="ok", template="Green", when=now - timedelta(hours=2)),
        _run(user, status="ok", template="Green", when=now - timedelta(hours=1)),
        _run(user, status="failed", template="Flaky", when=now - timedelta(hours=2)),
        _run(user, status="ok", template="Flaky", when=now - timedelta(hours=1)),
    ])
    await db.flush()

    r = await c.get("/api/analytics/templates")
    assert r.status_code == 200
    names = [it["template_name"] for it in r.json()["items"]]
    assert names == ["Flaky", "Green"]


async def test_other_users_personal_run_not_counted(db, make_user, session_for):
    other = await make_user(email="an3-other@example.com")
    viewer = await make_user(email="an3-viewer@example.com")
    # personal upload by another user (no team) -> invisible to viewer
    db.add(_run(other, status="failed", template="Secret", when=utcnow() - timedelta(hours=1)))
    await db.flush()
    c = await session_for(viewer)

    r = await c.get("/api/analytics/templates")
    assert r.status_code == 200
    assert r.json()["items"] == []


async def test_teammates_team_run_is_counted(db, make_user, session_for):
    # both users land in the default General team via make_user
    owner = await make_user(email="an-team-owner@example.com")
    viewer = await make_user(email="an-team-viewer@example.com")
    team = await db.scalar(select(Team).where(Team.is_default.is_(True)))
    db.add(_run(owner, status="failed", template="Shared",
                when=utcnow() - timedelta(hours=1), team_id=team.id))
    await db.flush()
    c = await session_for(viewer)

    r = await c.get("/api/analytics/templates")
    assert r.status_code == 200
    items = r.json()["items"]
    assert len(items) == 1
    assert items[0]["template_name"] == "Shared" and items[0]["runs"] == 1


async def test_all_failed_both_fail_statuses(db, make_user, session_for):
    # 'unreachable' counts as failure alongside 'failed'
    user = await make_user(email="an-allfail@example.com")
    c = await session_for(user)
    now = utcnow()
    db.add_all([
        _run(user, status="failed", when=now - timedelta(hours=2)),
        _run(user, status="unreachable", when=now - timedelta(hours=1)),
    ])
    await db.flush()

    r = await c.get("/api/analytics/templates")
    assert r.status_code == 200
    it = r.json()["items"][0]
    assert it["current_streak"] == 2 and it["streak_kind"] == "fail"
    assert it["time_to_recovery_s"] is None
    assert it["success_rate"] == 0.0 and it["failed"] == 2
    assert it["flaky_score"] == 0.0  # failed->unreachable is not a flip


async def test_flaky_score_max(db, make_user, session_for):
    user = await make_user(email="an-flaky@example.com")
    c = await session_for(user)
    now = utcnow()
    statuses = ["ok", "failed", "ok", "failed"]
    db.add_all([
        _run(user, status=s, when=now - timedelta(hours=4 - i))
        for i, s in enumerate(statuses)
    ])
    await db.flush()

    r = await c.get("/api/analytics/templates")
    assert r.status_code == 200
    it = r.json()["items"][0]
    assert it["flips"] == 3
    assert it["flaky_score"] == 1.0


async def test_window_excludes_old_runs(db, make_user, session_for):
    user = await make_user(email="an4@example.com")
    c = await session_for(user)
    now = utcnow()
    db.add_all([
        _run(user, status="ok", template="Win", when=now - timedelta(days=30)),
        _run(user, status="ok", template="Win", when=now - timedelta(hours=1)),
    ])
    await db.flush()

    r = await c.get("/api/analytics/templates?days=7")
    assert r.status_code == 200
    items = r.json()["items"]
    assert len(items) == 1 and items[0]["runs"] == 1


async def test_null_template_groups_as_untitled(db, make_user, session_for):
    user = await make_user(email="an5@example.com")
    c = await session_for(user)
    db.add(_run(user, status="ok", template=None, when=utcnow() - timedelta(hours=1)))
    await db.flush()

    r = await c.get("/api/analytics/templates")
    assert r.status_code == 200
    items = r.json()["items"]
    assert len(items) == 1 and items[0]["template_name"] == "(untitled)"


async def test_real_untitled_template_not_merged_with_null(db, make_user, session_for):
    # A run with no template (null) and a run whose template is literally "(untitled)"
    # must NOT be merged into one stats row — their per-template aggregates stay distinct.
    user = await make_user(email="an-untitled@example.com")
    c = await session_for(user)
    now = utcnow()
    db.add_all([
        _run(user, status="ok", template=None, when=now - timedelta(hours=2)),
        _run(user, status="failed", template="(untitled)", when=now - timedelta(hours=1)),
    ])
    await db.flush()

    r = await c.get("/api/analytics/templates")
    assert r.status_code == 200
    items = r.json()["items"]
    assert len(items) == 2
    # Distinct (un-merged) per-group success rates: one all-pass, one all-fail.
    assert sorted(it["success_rate"] for it in items) == [0.0, 1.0]
    assert all(it["runs"] == 1 for it in items)


async def test_unauthenticated_401(client):
    r = await client.get("/api/analytics/templates")
    assert r.status_code == 401


async def test_days_validation(db, make_user, session_for):
    user = await make_user(email="an6@example.com")
    c = await session_for(user)
    assert (await c.get("/api/analytics/templates?days=0")).status_code == 422
    assert (await c.get("/api/analytics/templates?days=366")).status_code == 422
