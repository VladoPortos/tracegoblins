"""Tests for app.awx.client — all AWX HTTP calls mocked with respx."""
from __future__ import annotations

import pytest
import respx
import httpx

import app.awx.client as client_module
from app.awx.client import AwxClient, AwxError, JobSummary, FINISHED_FILTER

BASE = "https://awx.example.com"
TOKEN = "testtoken123"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_client() -> AwxClient:
    return AwxClient(BASE, TOKEN, verify_ssl=False)


def _job(
    id: int,
    status: str = "successful",
    name: str = "Day2Actions",
    org_id: int | None = 1,
    org_name: str | None = "DXC",
    created_by: str | None = "cloudauto",
    launch_type: str = "scheduled",
    workflow_name: str | None = None,
    url: str | None = None,
) -> dict:
    sf: dict = {
        "job_template": {"id": 42, "name": name},
        "organization": {"id": org_id, "name": org_name} if org_id else {},
        "created_by": {"username": created_by} if created_by else {},
    }
    if workflow_name:
        sf["workflow_job"] = {"id": 99, "name": workflow_name}
    return {
        "id": id,
        "name": name,
        "status": status,
        "created": "2026-06-01T10:00:00.000000Z",
        "started": "2026-06-01T10:00:01.000000Z",
        "finished": "2026-06-01T10:05:00.000000Z",
        "elapsed": 299.0,
        "playbook": "site.yml",
        "launch_type": launch_type,
        "organization": org_id,
        "url": url or f"/api/v2/jobs/{id}/",
        "summary_fields": sf,
    }


def _page(results: list[dict], next_url: str | None = None) -> dict:
    return {"count": len(results), "next": next_url, "previous": None, "results": results}


# ---------------------------------------------------------------------------
# B2: package exports
# ---------------------------------------------------------------------------

def test_package_exports():
    from app.awx import AwxClient as C, AwxError as E, JobSummary as J
    assert C is AwxClient
    assert E is AwxError
    assert J is JobSummary


# ---------------------------------------------------------------------------
# AwxError
# ---------------------------------------------------------------------------

def test_awx_error_no_status():
    e = AwxError("conn failed")
    assert str(e) == "conn failed"
    assert e.status is None


def test_awx_error_with_status():
    e = AwxError("not found", status=404)
    assert e.status == 404


# ---------------------------------------------------------------------------
# JobSummary dataclass
# ---------------------------------------------------------------------------

def test_job_summary_frozen():
    js = JobSummary(
        id=1, name="t", status="successful", started=None,
        finished=None, elapsed=None, launch_type=None,
        organization_id=None, organization_name=None,
        created_by_username=None, workflow_name=None, url="/api/v2/jobs/1/",
    )
    with pytest.raises(Exception):
        js.id = 99  # type: ignore[misc]  # frozen dataclass


# ---------------------------------------------------------------------------
# ping()
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_ping_success():
    with respx.mock(base_url=BASE, assert_all_called=True) as mock:
        mock.get("/api/v2/ping/").mock(return_value=httpx.Response(
            200, json={"version": "24.6.1", "ha": False, "active_node": "awx-1"}
        ))
        mock.get("/api/v2/me/").mock(return_value=httpx.Response(
            200, json={"count": 1, "results": [{"username": "cloudauto"}]}
        ))
        async with _make_client() as client:
            result = await client.ping()
    assert result == {"version": "24.6.1", "identity": "cloudauto"}


@pytest.mark.asyncio
async def test_ping_empty_me_results():
    """Empty /me/ results -> identity=None (not a crash)."""
    with respx.mock(base_url=BASE) as mock:
        mock.get("/api/v2/ping/").mock(return_value=httpx.Response(
            200, json={"version": "24.6.1"}
        ))
        mock.get("/api/v2/me/").mock(return_value=httpx.Response(
            200, json={"count": 0, "results": []}
        ))
        async with _make_client() as client:
            result = await client.ping()
    assert result["identity"] is None


@pytest.mark.asyncio
async def test_ping_auth_failure():
    with respx.mock(base_url=BASE) as mock:
        mock.get("/api/v2/ping/").mock(return_value=httpx.Response(401, json={"detail": "Unauthorized"}))
        async with _make_client() as client:
            with pytest.raises(AwxError) as exc_info:
                await client.ping()
    assert exc_info.value.status == 401
    assert "authentication failed" in str(exc_info.value)


@pytest.mark.asyncio
async def test_ping_connect_error():
    with respx.mock(base_url=BASE) as mock:
        mock.get("/api/v2/ping/").mock(side_effect=httpx.ConnectError("refused"))
        async with _make_client() as client:
            with pytest.raises(AwxError) as exc_info:
                await client.ping()
    assert exc_info.value.status is None
    assert "Cannot reach AWX" in str(exc_info.value)


@pytest.mark.asyncio
async def test_ping_timeout():
    with respx.mock(base_url=BASE) as mock:
        mock.get("/api/v2/ping/").mock(side_effect=httpx.TimeoutException("timed out"))
        async with _make_client() as client:
            with pytest.raises(AwxError) as exc_info:
                await client.ping()
    assert exc_info.value.status is None


@pytest.mark.asyncio
async def test_ping_remote_protocol_error_is_normalized():
    with respx.mock(base_url=BASE) as mock:
        mock.get("/api/v2/ping/").mock(
            side_effect=httpx.RemoteProtocolError("peer closed connection")
        )
        async with _make_client() as client:
            with pytest.raises(AwxError) as exc_info:
                await client.ping()
    assert "Cannot reach AWX" in str(exc_info.value)


@pytest.mark.asyncio
async def test_ping_non_json_response():
    with respx.mock(base_url=BASE) as mock:
        mock.get("/api/v2/ping/").mock(return_value=httpx.Response(200, text="<html>not json</html>"))
        async with _make_client() as client:
            with pytest.raises(AwxError) as exc_info:
                await client.ping()
    assert "non-JSON" in str(exc_info.value)


@pytest.mark.asyncio
async def test_ping_rejects_non_object_json():
    with respx.mock(base_url=BASE) as mock:
        mock.get("/api/v2/ping/").mock(return_value=httpx.Response(200, json=[]))
        async with _make_client() as client:
            with pytest.raises(AwxError) as exc_info:
                await client.ping()
    assert "unexpected JSON shape" in str(exc_info.value)


@pytest.mark.asyncio
async def test_ping_http_error_500():
    with respx.mock(base_url=BASE) as mock:
        mock.get("/api/v2/ping/").mock(return_value=httpx.Response(500, json={"detail": "server error"}))
        async with _make_client() as client:
            with pytest.raises(AwxError) as exc_info:
                await client.ping()
    assert exc_info.value.status == 500


# ---------------------------------------------------------------------------
# list_jobs() — single page
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_list_jobs_single_page():
    jobs = [_job(101), _job(102, status="failed")]
    with respx.mock(base_url=BASE) as mock:
        mock.get(
            f"/api/v2/jobs/?id__gt=100&order_by=id&page_size=200{FINISHED_FILTER}"
        ).mock(return_value=httpx.Response(200, json=_page(jobs)))
        async with _make_client() as client:
            results = [js async for js in client.list_jobs(100)]

    assert len(results) == 2
    js = results[0]
    assert isinstance(js, JobSummary)
    assert js.id == 101
    assert js.name == "Day2Actions"
    assert js.status == "successful"
    assert js.organization_id == 1
    assert js.organization_name == "DXC"
    assert js.created_by_username == "cloudauto"
    assert js.launch_type == "scheduled"
    assert js.workflow_name is None
    assert js.url == "/api/v2/jobs/101/"
    assert js.elapsed == 299.0
    assert results[1].status == "failed"


@pytest.mark.asyncio
async def test_list_jobs_empty():
    with respx.mock(base_url=BASE) as mock:
        mock.get(
            f"/api/v2/jobs/?id__gt=0&order_by=id&page_size=200{FINISHED_FILTER}"
        ).mock(return_value=httpx.Response(200, json=_page([])))
        async with _make_client() as client:
            results = [js async for js in client.list_jobs(0)]
    assert results == []


@pytest.mark.asyncio
async def test_list_jobs_pagination():
    """Two pages: page1 has next pointing to page2."""
    page1_jobs = [_job(i) for i in range(201, 401)]  # 200 jobs
    page2_jobs = [_job(401)]
    next_url = f"{BASE}/api/v2/jobs/?id__gt=100&order_by=id&page_size=200&page=2{FINISHED_FILTER}"

    with respx.mock(base_url=BASE) as mock:
        mock.get(
            f"/api/v2/jobs/?id__gt=100&order_by=id&page_size=200{FINISHED_FILTER}"
        ).mock(return_value=httpx.Response(200, json=_page(page1_jobs, next_url=next_url)))
        # The client will re-request the full next_url
        mock.get(next_url).mock(return_value=httpx.Response(200, json=_page(page2_jobs)))

        async with _make_client() as client:
            results = [js async for js in client.list_jobs(100)]

    assert len(results) == 201
    assert results[0].id == 201
    assert results[-1].id == 401


@pytest.mark.asyncio
async def test_list_jobs_workflow_launch():
    """Job launched by a workflow has workflow_name set."""
    job = _job(200, launch_type="workflow", workflow_name="My Workflow")
    with respx.mock(base_url=BASE) as mock:
        mock.get(
            f"/api/v2/jobs/?id__gt=0&order_by=id&page_size=200{FINISHED_FILTER}"
        ).mock(return_value=httpx.Response(200, json=_page([job])))
        async with _make_client() as client:
            results = [js async for js in client.list_jobs(0)]
    assert results[0].workflow_name == "My Workflow"
    assert results[0].launch_type == "workflow"


@pytest.mark.asyncio
async def test_list_jobs_no_org_in_summary():
    """Job with no organization in summary_fields falls back to top-level organization field."""
    job = _job(300, org_id=5, org_name=None)
    # Remove organization from summary_fields to trigger fallback
    job["summary_fields"]["organization"] = {}
    with respx.mock(base_url=BASE) as mock:
        mock.get(
            f"/api/v2/jobs/?id__gt=0&order_by=id&page_size=200{FINISHED_FILTER}"
        ).mock(return_value=httpx.Response(200, json=_page([job])))
        async with _make_client() as client:
            results = [js async for js in client.list_jobs(0)]
    # org_id from top-level "organization" key
    assert results[0].organization_id == 5


@pytest.mark.asyncio
async def test_list_jobs_http_error():
    with respx.mock(base_url=BASE) as mock:
        mock.get(
            f"/api/v2/jobs/?id__gt=0&order_by=id&page_size=200{FINISHED_FILTER}"
        ).mock(return_value=httpx.Response(403, json={"detail": "Forbidden"}))
        async with _make_client() as client:
            with pytest.raises(AwxError) as exc_info:
                async for _ in client.list_jobs(0):
                    pass
    assert exc_info.value.status == 403


# ---------------------------------------------------------------------------
# get_job_events()
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_job_events_single_page():
    events = [
        {"counter": 1, "event": "playbook_on_start", "stdout": "PLAY [all]\n"},
        {"counter": 2, "event": "runner_on_ok", "stdout": "ok: [host1]\n"},
    ]
    with respx.mock(base_url=BASE) as mock:
        mock.get("/api/v2/jobs/42/job_events/?page_size=200&order_by=counter").mock(
            return_value=httpx.Response(200, json=_page(events))
        )
        async with _make_client() as client:
            result = await client.get_job_events(42)
    assert result == events


@pytest.mark.asyncio
async def test_get_job_events_paginated():
    page1_events = [{"counter": i, "event": "runner_on_ok", "stdout": f"event {i}\n"} for i in range(1, 201)]
    page2_events = [{"counter": 201, "event": "playbook_on_stats", "stdout": "PLAY RECAP\n"}]
    next_url = f"{BASE}/api/v2/jobs/7/job_events/?page_size=200&order_by=counter&page=2"

    with respx.mock(base_url=BASE) as mock:
        mock.get("/api/v2/jobs/7/job_events/?page_size=200&order_by=counter").mock(
            return_value=httpx.Response(200, json=_page(page1_events, next_url=next_url))
        )
        mock.get(next_url).mock(
            return_value=httpx.Response(200, json=_page(page2_events))
        )
        async with _make_client() as client:
            result = await client.get_job_events(7)

    assert len(result) == 201
    assert result[0]["counter"] == 1
    assert result[-1]["counter"] == 201


@pytest.mark.asyncio
async def test_get_job_events_empty():
    with respx.mock(base_url=BASE) as mock:
        mock.get("/api/v2/jobs/99/job_events/?page_size=200&order_by=counter").mock(
            return_value=httpx.Response(200, json=_page([]))
        )
        async with _make_client() as client:
            result = await client.get_job_events(99)
    assert result == []


@pytest.mark.asyncio
async def test_job_events_limit_allows_exact_boundary_without_next(monkeypatch):
    """Rejecting an exact final page would discard a complete job event stream."""
    monkeypatch.setattr(client_module, "MAX_JOB_EVENTS", 3)
    events = [{"counter": i, "event": "runner_on_ok", "stdout": "ok\n"} for i in range(1, 4)]
    with respx.mock(base_url=BASE) as mock:
        mock.get("/api/v2/jobs/7/job_events/?page_size=200&order_by=counter").mock(
            return_value=httpx.Response(200, json=_page(events))
        )
        async with _make_client() as client:
            assert len(await client.get_job_events(7)) == 3


@pytest.mark.asyncio
async def test_job_events_limit_rejects_partial_result_when_more_pages_exist(monkeypatch):
    """Removing the next-page guard would finalize the first three events as a whole run."""
    monkeypatch.setattr(client_module, "MAX_JOB_EVENTS", 3)
    events = [{"counter": i, "event": "runner_on_ok", "stdout": "ok\n"} for i in range(1, 4)]
    next_url = f"{BASE}/api/v2/jobs/7/job_events/?page_size=200&order_by=counter&page=2"
    with respx.mock(base_url=BASE) as mock:
        mock.get("/api/v2/jobs/7/job_events/?page_size=200&order_by=counter").mock(
            return_value=httpx.Response(200, json=_page(events, next_url=next_url))
        )
        async with _make_client() as client:
            with pytest.raises(AwxError, match="job 7.*3") as exc_info:
                await client.get_job_events(7)
    assert type(exc_info.value).__name__ == "AwxEventsLimitError"


@pytest.mark.asyncio
async def test_job_events_limit_rejects_oversized_final_page(monkeypatch):
    """Checking only next would accept a final page that itself exceeds the safety limit."""
    monkeypatch.setattr(client_module, "MAX_JOB_EVENTS", 3)
    events = [{"counter": i, "event": "runner_on_ok", "stdout": "ok\n"} for i in range(1, 5)]
    with respx.mock(base_url=BASE) as mock:
        mock.get("/api/v2/jobs/7/job_events/?page_size=200&order_by=counter").mock(
            return_value=httpx.Response(200, json=_page(events))
        )
        async with _make_client() as client:
            with pytest.raises(AwxError, match="job 7.*3") as exc_info:
                await client.get_job_events(7)
    assert type(exc_info.value).__name__ == "AwxEventsLimitError"


@pytest.mark.asyncio
async def test_get_job_events_auth_error():
    with respx.mock(base_url=BASE) as mock:
        mock.get("/api/v2/jobs/1/job_events/?page_size=200&order_by=counter").mock(
            return_value=httpx.Response(401, json={"detail": "Unauthorized"})
        )
        async with _make_client() as client:
            with pytest.raises(AwxError) as exc_info:
                await client.get_job_events(1)
    assert exc_info.value.status == 401
    assert "authentication failed" in str(exc_info.value)


# ---------------------------------------------------------------------------
# Authorization header
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_bearer_header_sent():
    """The Authorization: Bearer header is always sent."""
    captured_headers: dict = {}

    def capture(request: httpx.Request) -> httpx.Response:
        captured_headers.update(dict(request.headers))
        return httpx.Response(200, json={"version": "24.6.1"})

    with respx.mock(base_url=BASE) as mock:
        mock.get("/api/v2/ping/").mock(side_effect=capture)
        mock.get("/api/v2/me/").mock(return_value=httpx.Response(
            200, json={"count": 1, "results": [{"username": "u"}]}
        ))
        async with _make_client() as client:
            await client.ping()

    assert captured_headers.get("authorization") == f"Bearer {TOKEN}"


# ---------------------------------------------------------------------------
# verify_ssl passthrough
# ---------------------------------------------------------------------------

def test_verify_ssl_false_accepted():
    """AwxClient accepts verify_ssl=False without raising."""
    client = AwxClient(BASE, TOKEN, verify_ssl=False)
    # The httpx.AsyncClient is created; just check it's the right type
    assert isinstance(client._client, httpx.AsyncClient)


def test_verify_ssl_true_accepted():
    client = AwxClient(BASE, TOKEN, verify_ssl=True)
    assert isinstance(client._client, httpx.AsyncClient)


# ---------------------------------------------------------------------------
# last_list_count
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_list_jobs_sets_last_list_count(monkeypatch):
    from app.awx.client import AwxClient

    client = AwxClient("https://awx.example.com", "tok", False)
    page = {
        "count": 42,
        "next": None,
        "results": [
            {"id": 1, "status": "successful", "url": "/api/v2/jobs/1/", "summary_fields": {}},
            {"id": 2, "status": "failed", "url": "/api/v2/jobs/2/", "summary_fields": {}},
        ],
    }

    async def fake_get(url):
        return page

    monkeypatch.setattr(client, "_get_json", fake_get)
    jobs = [j async for j in client.list_jobs(0)]
    assert len(jobs) == 2
    assert client.last_list_count == 42
    await client._client.aclose()
