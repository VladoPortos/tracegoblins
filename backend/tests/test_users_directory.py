from __future__ import annotations

from sqlalchemy import select

from app.models import Team, User


async def test_users_search_returns_shared_team_members(authed_client, db, make_user):
    # member@ (authed_client) is in General; everyone make_user creates joins General too,
    # so they share a team and should be findable.
    other = await make_user(email="dir-find@example.com", display_name="Dana Directory")
    r = await authed_client.get("/api/users?q=dana")
    assert r.status_code == 200
    rows = r.json()
    assert any(u["id"] == str(other.id) and u["email"] == "dir-find@example.com" for u in rows)
    assert all(set(u.keys()) == {"id", "display_name", "email"} for u in rows)


async def test_users_search_matches_email_substring(authed_client, db, make_user):
    await make_user(email="needle-dir@example.com", display_name="Zoe")
    r = await authed_client.get("/api/users?q=needle-dir")
    assert r.status_code == 200
    assert any(u["email"] == "needle-dir@example.com" for u in r.json())


async def test_users_search_excludes_self(authed_client, db):
    me = await db.scalar(select(User).where(User.email == "member@example.com"))
    r = await authed_client.get("/api/users?q=member")
    assert all(u["id"] != str(me.id) for u in r.json())


async def test_users_search_excludes_non_shared_team_users(authed_client, db, make_user):
    # A user in a DISTINCT team (not General) with no overlap must not appear.
    t = Team(name="Solo Squad", slug="solo-squad")
    db.add(t)
    await db.flush()
    loner = await make_user(email="loner-dir@example.com", display_name="Lonnie", team=t)
    # `make_user(team=t)` joins ONLY team t (not General), so no shared team with member@.
    r = await authed_client.get("/api/users?q=lonnie")
    assert all(u["id"] != str(loner.id) for u in r.json())


async def test_users_search_requires_q_min_length(authed_client):
    assert (await authed_client.get("/api/users?q=")).status_code == 422
    assert (await authed_client.get("/api/users")).status_code == 422  # q required


async def test_users_search_requires_auth(client):
    # no session attached -> 401 (mirrors other authed endpoints)
    assert (await client.get("/api/users?q=a")).status_code == 401
