from datetime import datetime, timedelta, timezone

from app.models import Session as SessionModel


async def test_logout_revokes_current_session(authed_client):
    assert (await authed_client.get("/api/auth/me")).status_code == 200
    assert (await authed_client.post("/api/auth/logout")).status_code == 204
    assert (await authed_client.get("/api/auth/me")).status_code == 401


async def test_logout_everywhere_revokes_other_sessions(authed_client, db):
    me = await authed_client.get("/api/auth/me")
    user_id = me.json()["id"]
    # A second, independent session for the same user.
    other = SessionModel(id="second-session-token", user_id=user_id,
                         expires_at=datetime.now(timezone.utc) + timedelta(hours=1))
    db.add(other)
    await db.flush()
    assert (await authed_client.post("/api/auth/logout-everywhere")).status_code == 204
    from app.services.sessions import get_valid_session
    assert await get_valid_session(db, "second-session-token") is None
