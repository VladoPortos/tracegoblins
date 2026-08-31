"""Deterministic AWX 24.6.1 stand-in for the E2E flow (Task G3 runs it as a Docker
sidecar; the unit test in test_mock_awx_server.py drives it in-process via ASGITransport).

Serves exactly the four endpoints AwxClient hits, honoring the real query semantics:
`id__gt`, `order_by=id`, the finished-only `not__status=...` triplet, and DRF
page/page_size pagination. Bearer auth on everything except /ping/. No DB, no network out.
"""
from __future__ import annotations

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from tests.e2e.mock_awx_data import MOCK_JOB_EVENTS, MOCK_JOBS, MOCK_JOB_DETAILS, PROJECTS, paginate

_FINISHED = {"successful", "failed", "error", "canceled"}


def _unauthorized() -> JSONResponse:
    return JSONResponse({"detail": "Authentication credentials were not provided."}, status_code=401)


def _require_bearer(request: Request) -> bool:
    auth = request.headers.get("authorization", "")
    return auth.startswith("Bearer ") and len(auth) > len("Bearer ")


async def ping(request: Request) -> JSONResponse:
    return JSONResponse({"version": "24.6.1", "active_node": "mock", "ha": False})


async def me(request: Request) -> JSONResponse:
    if not _require_bearer(request):
        return _unauthorized()
    return JSONResponse({"count": 1, "next": None, "previous": None,
                         "results": [{"id": 1, "username": "cloudauto"}]})


async def jobs(request: Request) -> JSONResponse:
    if not _require_bearer(request):
        return _unauthorized()
    qp = request.query_params
    since = int(qp.get("id__gt", "0"))
    page = int(qp.get("page", "1"))
    page_size = int(qp.get("page_size", "200"))
    excluded = set(qp.getlist("not__status"))
    rows = [
        j for j in MOCK_JOBS
        if j["id"] > since
        and j["status"] in _FINISHED
        and j["status"] not in excluded
        and j["type"] == "job"
    ]
    rows.sort(key=lambda j: j["id"])  # order_by=id -> oldest first
    query = f"id__gt={since}&order_by=id"
    for s in sorted(excluded):
        query += f"&not__status={s}"
    return JSONResponse(paginate(rows, base="/api/v2/jobs/", page=page,
                                 page_size=page_size, query=query))


async def job_detail(request: Request) -> JSONResponse:
    if not _require_bearer(request):
        return _unauthorized()
    job_id = int(request.path_params["job_id"])
    detail = MOCK_JOB_DETAILS.get(job_id)
    if detail is None:
        return JSONResponse({"detail": "Not found."}, status_code=404)
    return JSONResponse(detail)


async def job_events(request: Request) -> JSONResponse:
    if not _require_bearer(request):
        return _unauthorized()
    job_id = int(request.path_params["job_id"])
    events = MOCK_JOB_EVENTS.get(job_id, [])
    page = int(request.query_params.get("page", "1"))
    page_size = int(request.query_params.get("page_size", "200"))
    base = f"/api/v2/jobs/{job_id}/job_events/"
    return JSONResponse(paginate(events, base=base, page=page,
                                 page_size=page_size, query="order_by=counter"))


async def projects(request: Request) -> JSONResponse:
    """Return the canned PROJECTS list so the sync mirrors project id 10 (Day2Actions)."""
    if not _require_bearer(request):
        return _unauthorized()
    page = int(request.query_params.get("page", "1"))
    page_size = int(request.query_params.get("page_size", "200"))
    return JSONResponse(paginate(PROJECTS, base="/api/v2/projects/", page=page,
                                 page_size=page_size))


def build_mock_awx() -> Starlette:
    return Starlette(routes=[
        Route("/api/v2/ping/", ping),
        Route("/api/v2/me/", me),
        Route("/api/v2/jobs/", jobs),
        Route("/api/v2/jobs/{job_id:int}/", job_detail),
        Route("/api/v2/jobs/{job_id:int}/job_events/", job_events),
        Route("/api/v2/projects/", projects),
    ])


# Module-level ASGI app so `uvicorn tests.e2e.mock_awx_server:app` works in the sidecar.
app = build_mock_awx()
