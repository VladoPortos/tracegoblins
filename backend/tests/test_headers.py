import pytest


@pytest.mark.asyncio
async def test_security_headers_present(client):
    r = await client.get("/api/health")
    csp = r.headers["content-security-policy"]
    assert "script-src 'self'" in csp
    assert "style-src 'self' 'unsafe-inline'" in csp  # design system uses inline styles
    assert "frame-ancestors 'none'" in csp
    assert "font-src 'self'" in csp
    assert r.headers["x-frame-options"] == "DENY"
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["referrer-policy"] == "strict-origin-when-cross-origin"
    assert "strict-transport-security" not in r.headers  # proxy owns HSTS


@pytest.mark.asyncio
async def test_headers_present_on_404(client):
    r = await client.get("/api/does-not-exist")
    assert r.status_code == 404
    assert "content-security-policy" in r.headers
