from app.main import app

EXPECTED = {
    ("GET", "/api/health"),
    ("GET", "/api/setup/status"),
    ("POST", "/api/setup"),
    ("GET", "/api/auth/csrf"),
    ("GET", "/api/auth/me"),
    ("POST", "/api/auth/login"),
    ("POST", "/api/auth/logout"),
    ("POST", "/api/auth/logout-everywhere"),
    ("POST", "/api/auth/change-password"),
    ("POST", "/api/admin/invites"),
    ("GET", "/api/invites/{token}"),
    ("POST", "/api/invites/{token}/accept"),
    ("GET", "/api/admin/users"),
    ("PATCH", "/api/admin/users/{user_id}/role"),
    ("POST", "/api/admin/users/{user_id}/deactivate"),
    ("POST", "/api/admin/users/{user_id}/activate"),
    ("GET", "/api/admin/teams"),
    ("POST", "/api/admin/teams"),
    ("PATCH", "/api/admin/teams/{team_id}"),
    ("POST", "/api/admin/teams/{team_id}/members"),
    ("DELETE", "/api/admin/teams/{team_id}/members/{user_id}"),
    ("DELETE", "/api/admin/teams/{team_id}"),
}


def test_all_routes_registered():
    # Derive from the OpenAPI schema (authoritative; stable across FastAPI's internal
    # app.routes representation — 0.137 wraps router includes in _IncludedRouter).
    _HTTP = {"get", "post", "put", "patch", "delete", "head", "options"}
    spec = app.openapi()["paths"]
    have = {
        (method.upper(), path)
        for path, ops in spec.items()
        for method in ops
        if method in _HTTP
    }
    missing = EXPECTED - have
    assert not missing, f"missing routes: {missing}"


def test_middleware_order_csrf_inside_headers():
    names = [m.cls.__name__ for m in app.user_middleware]
    # Starlette stores user_middleware outermost-first; SecurityHeaders must be outermost.
    assert names.index("SecurityHeadersMiddleware") < names.index("CSRFMiddleware")


def test_openapi_includes_meout():
    schema = app.openapi()
    assert "MeOut" in schema["components"]["schemas"]
