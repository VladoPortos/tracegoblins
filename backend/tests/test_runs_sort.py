"""Server-side sorting on GET /api/runs: validation, default, keys, nulls-last, dir."""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from app.models import Run


async def _u(make_user):
    return await make_user(email=f"sort-{uuid.uuid4().hex[:8]}@example.com")


async def _mk(db, owner, *, job_id=None, when=None, launched=None,
              hosts=0, elapsed=None, status_="successful"):
    r = Run(
        source="awx" if job_id is not None else "upload",
        owner_user_id=owner.id, team_id=None,
        awx_job_id=str(job_id) if job_id is not None else None,
        host_count=hosts, elapsed=elapsed, status=status_,
        log_time=when, launched_at=launched, recap=[],
    )
    db.add(r)
    await db.flush()
    return r


async def test_bad_sort_or_dir_is_422(client, db, make_user, session_for):
    u = await _u(make_user)
    mc = await session_for(u)
    assert (await mc.get("/api/runs?scope=mine&sort=bogus")).status_code == 422
    assert (await mc.get("/api/runs?scope=mine&dir=sideways")).status_code == 422


async def test_default_sort_is_when_desc(client, db, make_user, session_for):
    u = await _u(make_user)
    now = datetime.now(timezone.utc)
    old = await _mk(db, u, when=now - timedelta(days=2))
    new = await _mk(db, u, when=now)
    mc = await session_for(u)
    items = (await mc.get("/api/runs?scope=mine")).json()["items"]
    assert [i["id"] for i in items[:2]] == [str(new.id), str(old.id)]


async def test_when_prefers_launched_at(client, db, make_user, session_for):
    u = await _u(make_user)
    now = datetime.now(timezone.utc)
    a = await _mk(db, u, when=now - timedelta(days=5), launched=now)  # launched recent
    await _mk(db, u, when=now - timedelta(days=1))                   # log_time 1d ago, no launch
    mc = await session_for(u)
    items = (await mc.get("/api/runs?scope=mine&sort=when&dir=desc")).json()["items"]
    assert items[0]["id"] == str(a.id)


async def test_job_id_numeric_nulls_last(client, db, make_user, session_for):
    u = await _u(make_user)
    await _mk(db, u, job_id=842)
    await _mk(db, u, job_id=9)
    await _mk(db, u, job_id=100)
    await _mk(db, u, job_id=None)  # upload -> NULL job id
    mc = await session_for(u)
    items = (await mc.get("/api/runs?scope=mine&sort=job_id&dir=asc")).json()["items"]
    ids = [i["job_id"] for i in items]
    assert ids[:3] == ["9", "100", "842"]   # numeric, not lexical
    assert ids[-1] is None                  # NULL sorts last


async def test_duration_nulls_last_both_dirs(client, db, make_user, session_for):
    u = await _u(make_user)
    await _mk(db, u, elapsed=10.0)
    await _mk(db, u, elapsed=None)
    await _mk(db, u, elapsed=5.0)
    mc = await session_for(u)
    asc = (await mc.get("/api/runs?scope=mine&sort=duration&dir=asc")).json()["items"]
    assert [i["elapsed"] for i in asc] == [5.0, 10.0, None]
    desc = (await mc.get("/api/runs?scope=mine&sort=duration&dir=desc")).json()["items"]
    assert [i["elapsed"] for i in desc] == [10.0, 5.0, None]  # nulls still last


async def test_status_severity_order(client, db, make_user, session_for):
    u = await _u(make_user)
    await _mk(db, u, status_="ok")
    await _mk(db, u, status_="failed")
    await _mk(db, u, status_="unreachable")
    mc = await session_for(u)
    items = (await mc.get("/api/runs?scope=mine&sort=status&dir=asc")).json()["items"]
    assert items[0]["status"] == "unreachable"
    assert items[1]["status"] == "failed"


async def test_hosts_sort(client, db, make_user, session_for):
    u = await _u(make_user)
    await _mk(db, u, hosts=3)
    await _mk(db, u, hosts=30)
    mc = await session_for(u)
    items = (await mc.get("/api/runs?scope=mine&sort=hosts&dir=desc")).json()["items"]
    assert [i["host_count"] for i in items[:2]] == [30, 3]


async def test_job_id_overflow_digits_sort_last_no_500(client, db, make_user, session_for):
    # awx_job_id can come from uploaded-log content; a 25-digit value must NOT overflow
    # the bigint cast (would 500). It should be treated as unsortable -> NULL -> last.
    u = await _u(make_user)
    await _mk(db, u, job_id=5)
    huge = await _mk(db, u, job_id=None)
    huge.awx_job_id = "9" * 25  # pathological, > bigint range
    await db.flush()
    mc = await session_for(u)
    r = await mc.get("/api/runs?scope=mine&sort=job_id&dir=asc")
    assert r.status_code == 200  # no 500
    ids = [i["job_id"] for i in r.json()["items"]]
    assert ids[0] == "5"          # the valid numeric id sorts first
    assert ids[-1] == "9" * 25    # the overflow value sorts last (NULL bucket)
