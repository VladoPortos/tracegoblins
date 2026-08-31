from __future__ import annotations


def test_kb_router_registered():
    from app.main import app

    # Derive from the OpenAPI schema: authoritative and stable across FastAPI's
    # internal app.routes representation (0.137 wraps includes in _IncludedRouter).
    paths = set(app.openapi()["paths"])
    assert "/api/kb/signatures" in paths
    assert "/api/kb/signatures/{sig_id}" in paths
    assert "/api/kb/promote" in paths
    assert "/api/kb/signatures/{sig_id}/promote-global" in paths
    assert "/api/kb/suggest" in paths
    # the drawer endpoint lives on the runs router
    assert "/api/runs/{run_id}/tasks/{seq}/kb" in paths


def test_kb_router_has_prefix_and_tag():
    from app.api.kb import router

    assert router.prefix == "/api/kb"
    assert "kb" in router.tags


def test_kb_imports_are_acyclic():
    # Importing both routers in either order must not raise (no import cycle).
    import app.api.kb  # noqa: F401
    import app.api.runs  # noqa: F401
