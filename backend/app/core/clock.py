from __future__ import annotations

from datetime import datetime, timezone


def utcnow() -> datetime:
    """Aware UTC now — single definition shared by session/pending-login expiry math."""
    return datetime.now(timezone.utc)


def parse_iso(s: str | None) -> datetime | None:
    """ISO-8601 (``Z`` → ``+00:00``) → aware UTC datetime; None on absence/parse failure.
    A naive timestamp is assumed UTC so downstream subtraction is always aware-vs-aware.
    Single shared parser (was _parse_iso ×2 + a divergent job_events copy)."""
    if not s:
        return None
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)
