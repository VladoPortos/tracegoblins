from urllib.parse import urlsplit

_ALLOWED_SCHEMES = frozenset({"http", "https", "mailto"})


def is_safe_url(value: str) -> bool:
    """True only for http(s)/mailto absolute URLs. Blocks javascript:, data:, etc."""
    if not value or len(value) > 2048:
        return False
    try:
        parts = urlsplit(value.strip())
    except ValueError:
        return False
    scheme = parts.scheme.lower()
    if scheme not in _ALLOWED_SCHEMES:
        return False
    if scheme in {"http", "https"} and not parts.netloc:
        return False
    return True


def sanitize_url(value: str) -> str | None:
    return value.strip() if is_safe_url(value) else None
