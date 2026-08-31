async def test_unknown_api_path_is_json_404(client):
    r = await client.get("/api/definitely-not-a-route")
    assert r.status_code == 404
    assert r.headers["content-type"].startswith("application/json")


async def test_index_html_is_no_cache_so_deploys_take_effect(tmp_path):
    # index.html references content-hashed bundles → it must revalidate every load, else a cached
    # index keeps pointing at an old (deleted) bundle after a deploy → stale/broken SPA.
    import httpx
    from fastapi import FastAPI
    from app.static import mount_spa

    (tmp_path / "index.html").write_text("<!doctype html><html><body>spa</body></html>")
    (tmp_path / "assets").mkdir()
    (tmp_path / "assets" / "index-abc123.js").write_text("console.log(1)")

    app = FastAPI()
    mount_spa(app, str(tmp_path))
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
        # the SPA entry (root) and a client-side route both serve index.html with no-cache
        for path in ("/", "/runs/123/path"):
            r = await c.get(path)
            assert r.status_code == 200
            assert "spa" in r.text
            assert r.headers.get("cache-control") == "no-cache", path
