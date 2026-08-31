from datetime import datetime, timedelta, timezone

from sqlalchemy import event

from app.models import Session as SessionModel


async def test_non_admin_forbidden(authed_client):
    assert (await authed_client.get("/api/admin/users")).status_code == 403


async def test_admin_lists_users(admin_client, make_user):
    await make_user(email="listed@example.com")
    r = await admin_client.get("/api/admin/users")
    assert r.status_code == 200
    body = r.json()
    emails = {u["email"] for u in body}
    assert "listed@example.com" in emails
    # Canonical wire format: tz-aware datetimes serialize with a 'Z' suffix.
    assert body[0]["created_at"].endswith("Z")


async def test_admin_user_list_batches_team_memberships(admin_client, make_user, db):
    await make_user(email="batch-one@example.com")
    await make_user(email="batch-two@example.com")
    statements: list[str] = []

    def record(_conn, _cursor, statement, _parameters, _context, _executemany):
        statements.append(statement.lower())

    target = db.bind.sync_connection
    event.listen(target, "before_cursor_execute", record)
    try:
        response = await admin_client.get("/api/admin/users")
    finally:
        event.remove(target, "before_cursor_execute", record)

    assert response.status_code == 200
    membership_queries = [
        sql for sql in statements
        if "team_members" in sql and "teams" in sql and " join " in sql
        and "team_members.user_id" in sql
    ]
    assert len(membership_queries) == 1


async def test_admin_changes_role(admin_client, make_user, db):
    u = await make_user(email="promote@example.com", role="user")
    r = await admin_client.patch(f"/api/admin/users/{u.id}/role", json={"role": "admin"})
    assert r.status_code == 200 and r.json()["role"] == "admin"


async def test_change_role_invalid_value_returns_422(admin_client, make_user):
    # Exercises the manual 422 branch in change_role: must return 422 cleanly, not
    # raise (the constant is HTTP_422_UNPROCESSABLE_CONTENT, not the deprecated name
    # that warns-as-error under filterwarnings=["error::DeprecationWarning"]).
    u = await make_user(email="badrole@example.com", role="user")
    r = await admin_client.patch(f"/api/admin/users/{u.id}/role", json={"role": "superuser"})
    assert r.status_code == 422


async def test_deactivate_revokes_sessions(admin_client, make_user, db):
    u = await make_user(email="deact@example.com")
    db.add(SessionModel(id="deact-session", user_id=u.id,
                        expires_at=datetime.now(timezone.utc) + timedelta(hours=1)))
    await db.flush()
    r = await admin_client.post(f"/api/admin/users/{u.id}/deactivate")
    assert r.status_code == 200 and r.json()["is_active"] is False
    from app.services.sessions import get_valid_session
    assert await get_valid_session(db, "deact-session") is None


async def test_password_change_gate_blocks_admin_endpoints(make_user, session_for):
    admin = await make_user(email="must@example.com", role="admin", must_change_password=True)
    c = await session_for(admin)
    r = await c.get("/api/admin/users")
    assert r.status_code == 403
    assert r.json()["detail"]["code"] == "password_change_required"


async def test_cannot_demote_last_admin(admin_client):
    me = (await admin_client.get("/api/auth/me")).json()
    r = await admin_client.patch(f"/api/admin/users/{me['id']}/role", json={"role": "user"})
    assert r.status_code == 409  # last-admin guard


async def test_can_demote_when_another_admin_exists(admin_client, make_user, db):
    other = await make_user(email="second-admin@example.com", role="admin")
    r = await admin_client.patch(f"/api/admin/users/{other.id}/role", json={"role": "user"})
    assert r.status_code == 200 and r.json()["role"] == "user"


async def test_admin_users_list_includes_avatar_fields(admin_client, make_user, db):
    """Admin users list exposes initials/avatar_color so the UI can render stored avatars."""
    u = await make_user(email="avatar@example.com")
    u.initials = "AV"
    u.avatar_color = "#ff8800"
    await db.flush()

    r = await admin_client.get("/api/admin/users")
    assert r.status_code == 200
    users = {usr["email"]: usr for usr in r.json()}

    assert users["avatar@example.com"]["initials"] == "AV"
    assert users["avatar@example.com"]["avatar_color"] == "#ff8800"


async def test_admin_users_list_includes_totp_enabled(admin_client, make_user, db):
    """Admin users list exposes totp_enabled; a user with 2FA on shows totp_enabled: true."""
    u = await make_user(email="totp-on@example.com")
    u.totp_enabled = True
    await db.flush()

    r = await admin_client.get("/api/admin/users")
    assert r.status_code == 200
    users = {usr["email"]: usr for usr in r.json()}

    # User with 2FA on
    assert "totp-on@example.com" in users
    assert users["totp-on@example.com"]["totp_enabled"] is True

    # At least one user without 2FA should have totp_enabled: false
    other = next((usr for usr in r.json() if not usr["email"].startswith("totp-on")), None)
    if other is not None:
        assert other["totp_enabled"] is False
