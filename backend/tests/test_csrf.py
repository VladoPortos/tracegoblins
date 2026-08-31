import pytest


@pytest.mark.asyncio
async def test_get_sets_csrf_cookie(client):
    from app.core.config import settings

    r = await client.get("/api/auth/csrf")
    assert r.status_code == 200
    assert settings.csrf_cookie_name in r.cookies


@pytest.mark.asyncio
async def test_mutation_without_header_is_forbidden(authed_client):
    from app.core.config import settings

    # authed_client carries a valid session; drop the CSRF header but keep cookie.
    authed_client.headers.pop(settings.csrf_header_name, None)
    r = await authed_client.post("/api/auth/logout")
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_mutation_with_mismatched_header_is_forbidden(authed_client):
    from app.core.config import settings

    authed_client.headers[settings.csrf_header_name] = "does-not-match-cookie"
    r = await authed_client.post("/api/auth/logout")
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_setup_is_csrf_exempt(client):
    # /api/setup must work on an empty DB before any cookie/CSRF token exists.
    r = await client.post("/api/setup", json={
        "email": "first@admin.test", "display_name": "First", "password": "sup3r-s3cret-pw",
    })
    # Not a 403 (CSRF). Will be 201 once Task 16 lands; until then 404/405 is acceptable here.
    assert r.status_code != 403


def test_csrf_names_are_fixed_and_not_env_overridable(monkeypatch):
    """Regression (F5): the CSRF cookie/header names must match the SPA's hard-coded literals and
    must NOT be env-overridable — an override would 403 every frontend mutation (incl. uploads)."""
    from app.core.config import Settings, settings

    # Defaults equal the literals the built-in SPA sends (frontend/src/api/client.ts).
    assert settings.csrf_cookie_name == "csrf_token"
    assert settings.csrf_header_name == "X-CSRF-Token"

    # Even with env vars set, a freshly-constructed Settings keeps the hard-coded names (ClassVar,
    # so they are not part of the BaseSettings env-bound field set).
    monkeypatch.setenv("CSRF_COOKIE_NAME", "evil_csrf")
    monkeypatch.setenv("CSRF_HEADER_NAME", "X-Evil")
    fresh = Settings()
    assert fresh.csrf_cookie_name == "csrf_token"
    assert fresh.csrf_header_name == "X-CSRF-Token"
