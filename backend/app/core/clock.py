from __future__ import annotations

from datetime import datetime, timezone


def utcnow() -> datetime:
    """Aware UTC now — single definition shared by session/pending-login expiry math."""
    return datetime.now(timezone.utc)
