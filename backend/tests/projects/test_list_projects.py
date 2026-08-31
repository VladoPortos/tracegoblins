from __future__ import annotations

import httpx
import pytest
import respx

from app.awx.client import AwxClient, AwxError, ProjectSummary

BASE = "https://awx.example.com"
TOKEN = "testtoken123"


def _proj(pid: int, name: str, org_id: int | None = 2, org_name: str | None = "DXC") -> dict:
    sf: dict = {"organization": {"id": org_id, "name": org_name} if org_id else {}}
    return {
        "id": pid, "name": name, "description": "", "scm_type": "git",
        "scm_url": f"https://git.example.com/{name}.git", "scm_branch": "main",
        "scm_revision": "a" * 40, "status": "successful",
        "organization": org_id, "summary_fields": sf,
    }


def _page(results: list[dict], next_url: str | None = None) -> dict:
    return {"count": len(results), "next": next_url, "previous": None, "results": results}


@respx.mock
async def test_list_projects_paginates_and_maps():
    p1 = f"{BASE}/api/v2/projects/?page_size=200&order_by=id"
    p2 = f"{BASE}/api/v2/projects/?page_size=200&order_by=id&page=2"
    respx.get(p1).mock(return_value=httpx.Response(200, json=_page([_proj(19, "day2")], next_url=p2)))
    respx.get(p2).mock(return_value=httpx.Response(200, json=_page([_proj(10, "hpc", org_id=None, org_name=None)])))

    async with AwxClient(BASE, TOKEN, verify_ssl=False) as c:
        out = await c.list_projects()

    assert [p.id for p in out] == [19, 10]
    assert out[0] == ProjectSummary(
        id=19, name="day2", description=None, scm_type="git",
        scm_url="https://git.example.com/day2.git", scm_branch="main",
        scm_revision="a" * 40, status="successful", organization_id=2, organization_name="DXC",
    )
    assert out[1].organization_id is None and out[1].organization_name is None


@respx.mock
async def test_list_projects_rejects_offorigin_next():
    p1 = f"{BASE}/api/v2/projects/?page_size=200&order_by=id"
    evil = "https://evil.example.net/api/v2/projects/?page=2"
    respx.get(p1).mock(return_value=httpx.Response(200, json=_page([_proj(19, "day2")], next_url=evil)))
    async with AwxClient(BASE, TOKEN, verify_ssl=False) as c:
        with pytest.raises(AwxError):
            await c.list_projects()
