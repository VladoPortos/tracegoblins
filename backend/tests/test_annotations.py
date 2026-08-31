from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
UPLOADS = ROOT / "backend/tests/fixtures/logs"


async def _upload(client) -> str:
    text = (UPLOADS / "job_11140.txt").read_text(encoding="utf-8")
    r = await client.post("/api/runs", json={"text": text})
    assert r.status_code == 201
    return r.json()["id"]


async def test_create_and_list_annotation_on_own_run(authed_client):
    rid = await _upload(authed_client)
    body = {"note": "needs a retry", "tags": ["needs-fix"],
            "links": [{"label": "ticket", "url": "https://jira/AB-1"}]}
    r = await authed_client.post(f"/api/runs/{rid}/tasks/1/annotations", json=body)
    assert r.status_code == 201
    a = r.json()
    assert a["task_seq"] == 1 and a["note"] == "needs a retry"
    assert a["tags"] == ["needs-fix"] and a["resolved"] is False
    assert a["links"] == [{"label": "ticket", "url": "https://jira/AB-1"}]
    assert a["author_name"] == "member"  # display_name from email local-part

    lst = await authed_client.get(f"/api/runs/{rid}/annotations")
    assert lst.status_code == 200
    items = lst.json()
    assert len(items) == 1 and items[0]["id"] == a["id"]


async def test_create_annotation_rejects_unknown_tag(authed_client):
    rid = await _upload(authed_client)
    r = await authed_client.post(f"/api/runs/{rid}/tasks/1/annotations",
                                 json={"note": "x", "tags": ["bogus"]})
    assert r.status_code == 422


async def test_create_annotation_rejects_javascript_link(authed_client):
    rid = await _upload(authed_client)
    r = await authed_client.post(
        f"/api/runs/{rid}/tasks/1/annotations",
        json={"note": "x", "links": [{"label": "evil", "url": "javascript:alert(1)"}]})
    assert r.status_code == 422


async def test_create_annotation_rejects_data_uri_link(authed_client):
    rid = await _upload(authed_client)
    r = await authed_client.post(
        f"/api/runs/{rid}/tasks/1/annotations",
        json={"note": "x", "links": [{"label": "evil", "url": "data:text/html,<script>"}]})
    assert r.status_code == 422


async def test_create_annotation_allows_mailto_link(authed_client):
    rid = await _upload(authed_client)
    r = await authed_client.post(
        f"/api/runs/{rid}/tasks/1/annotations",
        json={"note": "x", "links": [{"label": "mail", "url": "mailto:ops@example.com"}]})
    assert r.status_code == 201


async def test_non_visible_user_cannot_list_or_create_annotation(authed_client, make_user, session_for):
    rid = await _upload(authed_client)
    snoop = await make_user(email="snoop-ann@example.com")
    sc = await session_for(snoop)
    assert (await sc.get(f"/api/runs/{rid}/annotations")).status_code == 404
    assert (await sc.post(f"/api/runs/{rid}/tasks/1/annotations",
                          json={"note": "x"})).status_code == 404
