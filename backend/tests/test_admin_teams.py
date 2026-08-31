from sqlalchemy import event, func, select

from app.models import Team, TeamMember


async def test_admin_creates_and_renames_team(admin_client, db):
    r = await admin_client.post("/api/admin/teams", json={"name": "Platform"})
    assert r.status_code == 201
    tid = r.json()["id"]
    assert r.json()["slug"] == "platform"

    rn = await admin_client.patch(f"/api/admin/teams/{tid}", json={"name": "Platform Eng"})
    assert rn.status_code == 200 and rn.json()["name"] == "Platform Eng"


async def test_list_teams_has_member_count(admin_client, db):
    await admin_client.post("/api/admin/teams", json={"name": "Counted"})
    r = await admin_client.get("/api/admin/teams")
    assert r.status_code == 200
    assert any(t["name"] == "Counted" and t["member_count"] == 0 for t in r.json())


async def test_admin_team_list_batches_member_counts(admin_client, db):
    await admin_client.post("/api/admin/teams", json={"name": "Batch A"})
    await admin_client.post("/api/admin/teams", json={"name": "Batch B"})
    statements: list[str] = []

    def record(_conn, _cursor, statement, _parameters, _context, _executemany):
        statements.append(statement.lower())

    target = db.bind.sync_connection
    event.listen(target, "before_cursor_execute", record)
    try:
        response = await admin_client.get("/api/admin/teams")
    finally:
        event.remove(target, "before_cursor_execute", record)

    assert response.status_code == 200
    count_queries = [
        sql for sql in statements
        if "from team_members" in sql and "count(" in sql
    ]
    assert len(count_queries) == 1


async def test_add_and_remove_member(admin_client, make_user, db):
    u = await make_user(email="tm@example.com")  # already in General
    t = (await admin_client.post("/api/admin/teams", json={"name": "Squad"})).json()
    add = await admin_client.post(f"/api/admin/teams/{t['id']}/members", json={"user_id": str(u.id)})
    assert add.status_code == 204
    # now in 2 teams; removing Squad is allowed
    rem = await admin_client.delete(f"/api/admin/teams/{t['id']}/members/{u.id}")
    assert rem.status_code == 204


async def test_cannot_remove_users_last_team(admin_client, make_user, db):
    u = await make_user(email="last@example.com")  # only in General
    general = await db.scalar(select(Team).where(Team.is_default.is_(True)))
    r = await admin_client.delete(f"/api/admin/teams/{general.id}/members/{u.id}")
    assert r.status_code == 409
    assert await db.scalar(
        select(func.count()).select_from(TeamMember).where(TeamMember.user_id == u.id)
    ) == 1


async def test_cannot_delete_default_team(admin_client, db):
    general = await db.scalar(select(Team).where(Team.is_default.is_(True)))
    r = await admin_client.delete(f"/api/admin/teams/{general.id}")
    assert r.status_code == 409


async def test_delete_empty_team_ok(admin_client, db):
    t = (await admin_client.post("/api/admin/teams", json={"name": "Temp"})).json()
    r = await admin_client.delete(f"/api/admin/teams/{t['id']}")
    assert r.status_code == 204


async def test_add_member_rejects_non_uuid(admin_client, db):
    t = (await admin_client.post("/api/admin/teams", json={"name": "Sq"})).json()
    r = await admin_client.post(f"/api/admin/teams/{t['id']}/members", json={"user_id": "not-a-uuid"})
    assert r.status_code == 422
