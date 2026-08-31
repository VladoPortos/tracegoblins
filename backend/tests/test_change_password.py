from datetime import datetime, timedelta, timezone

from app.models import Session as SessionModel
from app.services.sessions import get_valid_session


async def test_change_password_revokes_other_sessions_not_current(authed_client, db):
    # Find out the current user's id.
    me = await authed_client.get("/api/auth/me")
    user_id = me.json()["id"]

    # Insert a second session for the same user directly.
    db.add(SessionModel(
        id="other-session-token",
        user_id=user_id,
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
    ))
    await db.flush()

    # Change password using the current (authed) session.
    r = await authed_client.post("/api/auth/change-password", json={
        "current_password": "hunter2hunter2",
        "new_password": "brand-new-password-xyz",
    })
    assert r.status_code == 204

    # The second session must now be revoked.
    assert await get_valid_session(db, "other-session-token") is None

    # The caller's own session must still be valid.
    assert (await authed_client.get("/api/auth/me")).status_code == 200


async def test_change_password_wrong_current_400(authed_client):
    r = await authed_client.post("/api/auth/change-password", json={
        "current_password": "not-the-current", "new_password": "a-fresh-password-99",
    })
    assert r.status_code == 400


async def test_change_password_succeeds_and_clears_flag(client, csrf, make_user, db):
    await make_user(email="cp@example.com", password="old-password-1234", must_change_password=True)
    c = await csrf()
    await c.post("/api/auth/login", json={"email": "cp@example.com", "password": "old-password-1234"})
    # logged-in client now holds the session cookie + csrf header
    r = await c.post("/api/auth/change-password", json={
        "current_password": "old-password-1234", "new_password": "brand-new-password-99",
    })
    assert r.status_code == 204
    me = await c.get("/api/auth/me")
    assert me.json()["must_change_password"] is False
    # Old password no longer works.
    c2 = await csrf()
    bad = await c2.post("/api/auth/login", json={"email": "cp@example.com", "password": "old-password-1234"})
    assert bad.status_code == 401
