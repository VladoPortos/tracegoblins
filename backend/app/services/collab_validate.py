from __future__ import annotations

from fastapi import HTTPException, status

from app.api.collab_schemas import TAG_VALUES, AnnotationLink
from app.security.urls import is_safe_url


def validate_tags(tags: list[str]) -> list[str]:
    """Return tags unchanged if every value is in TAG_VALUES, else 422."""
    bad = [t for t in tags if t not in TAG_VALUES]
    if bad:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"Unknown tag(s): {', '.join(sorted(set(bad)))}",
        )
    return tags


def validate_links(links: list[AnnotationLink]) -> list[dict[str, str]]:
    """Validate each link url with the canonical is_safe_url (scheme allowlist + netloc +
    length). One helper, one rule — shared with the rest of the app. Returns JSONB-ready dicts."""
    out: list[dict[str, str]] = []
    for lk in links:
        if not is_safe_url(lk.url):
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=f"URL is not a valid/allowed link: {lk.url[:80]!r}",
            )
        out.append({"label": lk.label, "url": lk.url.strip()})
    return out
