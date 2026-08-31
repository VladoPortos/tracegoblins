import pytest

from app.security.urls import is_http_url, is_safe_url


@pytest.mark.parametrize("url", [
    "https://example.com", "http://example.com/a", "mailto:a@b.c",
])
def test_allows_safe(url):
    assert is_safe_url(url) is True


@pytest.mark.parametrize("url", [
    "javascript:alert(1)", "data:text/html,x", "vbscript:x", "file:///etc/passwd",
    "  javascript:alert(1)", "//evil.com", "http:evil", "", "x" * 3000,
])
def test_blocks_unsafe(url):
    assert is_safe_url(url) is False


@pytest.mark.parametrize("url", [
    "http://awx.example.com", "https://awx.example.com/", "http://1.2.3.4:8080",
    "https://[::1]:443/api", "http://host:65535", "  https://awx.example.com  ",
])
def test_http_url_accepts_valid(url):
    assert is_http_url(url) is True


@pytest.mark.parametrize("url", [
    "http://[::1",             # F4: unterminated IPv6 -> urlsplit ValueError (was uncaught -> 500)
    "http://example.com:bad",  # F4: non-numeric port -> passed validation -> httpx InvalidURL -> 500
    "http://host:99999",       # out-of-range port
    "http://host:-1",
    "ftp://example.com", "mailto:a@b.c", "javascript:alert(1)", "", "//evil.com", "notaurl",
])
def test_http_url_rejects_invalid_without_raising(url):
    # Must return False (-> clean 422), never raise (which previously escaped as HTTP 500).
    assert is_http_url(url) is False
