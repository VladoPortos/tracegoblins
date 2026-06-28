"""Canonical Ansible task/host status vocabulary — ONE source of truth.

Previously duplicated as `_RANK`/`_ITEM_RANK` (4-5 copies), `STATUS_ORDER`, and several
ad-hoc `{"failed", "unreachable"}` sets across logparser/services/api. Import from here so a
new status (or a re-ranking) is a one-line change, not a scavenger hunt.
"""
from __future__ import annotations

# Severity rank: higher = worse. `skipped`/`included` are non-significant; failures rank highest.
# Only the RELATIVE order matters (callers compare, never use the literal int).
RANK: dict[str, int] = {
    "skipped": 0, "included": 1, "ok": 2, "changed": 3, "failed": 4, "unreachable": 5,
}

# Worst-first ordering (the inverse of RANK) for "pick the dominant status present" loops.
STATUS_ORDER: list[str] = ["unreachable", "failed", "changed", "ok", "included", "skipped"]

# A task/host with one of these did not succeed.
FAIL_STATUSES: frozenset[str] = frozenset({"failed", "unreachable"})
# A run/task in one of these is "green" (success-ish) — used for diff baselines + success rate.
GREEN_STATUSES: frozenset[str] = frozenset({"ok", "changed", "skipped"})


def rank(status: str) -> int:
    return RANK.get(status, 0)


def worst(a: str, b: str) -> str:
    """The more severe of two statuses (ties keep `a`)."""
    return a if rank(a) >= rank(b) else b
