async def test_me_requires_auth(client):
    r = await client.get("/api/auth/me")
    assert r.status_code == 401


async def test_me_returns_user_with_teams(authed_client):
    r = await authed_client.get("/api/auth/me")
    assert r.status_code == 200
    body = r.json()
    assert body["email"] == "member@example.com"
    assert body["role"] == "user"
    assert any(t["is_default"] for t in body["teams"])  # General membership


async def test_me_rejects_tampered_cookie(authed_client):
    from app.core.config import settings
    authed_client.cookies.set(settings.session_cookie_name, "garbage.tampered.value")
    r = await authed_client.get("/api/auth/me")
    assert r.status_code == 401


async def test_admin_client_is_admin(admin_client):
    r = await admin_client.get("/api/auth/me")
    assert r.json()["role"] == "admin"
