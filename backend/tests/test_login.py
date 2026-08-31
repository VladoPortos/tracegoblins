async def test_login_success_sets_cookie_and_returns_me(client, csrf, make_user):
    await make_user(email="login@example.com", password="the-real-password-1")
    c = await csrf()
    r = await c.post("/api/auth/login", json={
        "email": "login@example.com", "password": "the-real-password-1",
    })
    assert r.status_code == 200
    assert r.json()["email"] == "login@example.com"
    from app.core.config import settings
    assert settings.session_cookie_name in r.cookies


async def test_login_wrong_password_401(client, csrf, make_user):
    await make_user(email="wp@example.com", password="the-real-password-1")
    c = await csrf()
    r = await c.post("/api/auth/login", json={"email": "wp@example.com", "password": "nope-nope-nope"})
    assert r.status_code == 401


async def test_login_unknown_email_401(client, csrf):
    c = await csrf()
    r = await c.post("/api/auth/login", json={"email": "ghost@example.com", "password": "whatever-1234"})
    assert r.status_code == 401


async def test_login_inactive_user_401(client, csrf, make_user, db):
    u = await make_user(email="inactive@example.com", password="the-real-password-1")
    u.is_active = False
    await db.flush()
    c = await csrf()
    r = await c.post("/api/auth/login", json={"email": "inactive@example.com", "password": "the-real-password-1"})
    assert r.status_code == 401


async def test_login_rate_limit_locks_out(client, csrf, make_user):
    await make_user(email="victim@example.com", password="the-real-password-1")
    c = await csrf()
    bad = {"email": "victim@example.com", "password": "wrong-wrong-wrong"}
    for _ in range(5):
        assert (await c.post("/api/auth/login", json=bad)).status_code == 401
    locked = await c.post("/api/auth/login", json=bad)
    assert locked.status_code == 429
    assert locked.headers.get("retry-after")
    # Correct password is still refused while locked.
    good = await c.post("/api/auth/login", json={"email": "victim@example.com", "password": "the-real-password-1"})
    assert good.status_code == 429
