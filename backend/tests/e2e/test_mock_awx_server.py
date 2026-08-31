import httpx
import pytest

from app.awx.client import AwxClient
from tests.e2e.mock_awx_server import build_mock_awx


@pytest.fixture
def transport():
    return httpx.ASGITransport(app=build_mock_awx())


async def _client(transport) -> AwxClient:
    c = AwxClient("http://mock-awx", "tok-abc", verify_ssl=False)
    # swap the underlying httpx client onto the ASGI transport (no network)
    await c._client.aclose()
    c._client = httpx.AsyncClient(
        base_url="http://mock-awx", transport=transport,
        headers={"Authorization": "Bearer tok-abc", "Accept": "application/json"},
    )
    return c


async def test_ping_reports_version_and_identity(transport):
    async with await _client(transport) as c:
        out = await c.ping()
    assert out == {"version": "24.6.1", "identity": "cloudauto"}


async def test_list_jobs_finished_only_oldest_first_paginated(transport):
    async with await _client(transport) as c:
        jobs = [j async for j in c.list_jobs(since_id=0)]
    assert [j.id for j in jobs] == [743, 744, 745]          # oldest -> newest
    assert jobs[-1].status == "failed"
    assert jobs[0].organization_name == "DXC"
    assert jobs[0].name == "Day2Actions"


async def test_list_jobs_honors_cursor(transport):
    async with await _client(transport) as c:
        jobs = [j async for j in c.list_jobs(since_id=744)]
    assert [j.id for j in jobs] == [745]


async def test_get_job_events_returns_counter_ordered_events(transport):
    async with await _client(transport) as c:
        events = await c.get_job_events(745)
    assert [e["counter"] for e in events] == [1, 2, 3, 4, 5, 6, 7]
    assert any(e["event"] == "runner_on_failed" for e in events)


async def test_ping_requires_no_auth_but_jobs_require_bearer():
    app = build_mock_awx()
    t = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(base_url="http://mock-awx", transport=t) as raw:
        assert (await raw.get("/api/v2/ping/")).status_code == 200
        # no Authorization header -> 401 on an authed endpoint
        assert (await raw.get("/api/v2/jobs/")).status_code == 401
