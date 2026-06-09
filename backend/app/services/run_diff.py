"""Diff a run against its last green baseline (same template, older, visible).

`find_baseline` is the only DB-touching function; `diff_tasks` and
`recap_newly_unreachable` are pure so they stay unit-testable without a DB.
"""

from __future__ import annotations

from typing import Any, Iterable, Sequence

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.runs_schemas import DiffEntry, DurationDelta
from app.models import Run, User
from app.services.visibility import run_visible_cond

FAIL = {"failed", "unreachable"}
GREEN = ("ok", "changed")
MAX_ENTRIES = 200          # hard cap per entry list — never unbounded
MIN_DURATION_DELTA_S = 5.0  # ignore sub-5s task duration noise
TOP_SLOWEST = 5


async def find_baseline(db: AsyncSession, run: Run, user: User) -> Run | None:
    """The most recent VISIBLE green run of the same template strictly older than `run`.

    Effective time is coalesce(launched_at, log_time, created_at) on both sides.
    Visibility uses the canonical single-viewer predicate (A1: admin grants nothing).
    """
    if run.template_name is None:
        return None
    run_when = run.launched_at or run.log_time or run.created_at
    when = func.coalesce(Run.launched_at, Run.log_time, Run.created_at)
    visible = await run_visible_cond(db, user)
    return await db.scalar(
        select(Run)
        .where(
            visible,
            Run.id != run.id,
            Run.template_name == run.template_name,
            Run.status.in_(GREEN),
            when < run_when,
        )
        .order_by(when.desc(), Run.id.asc())
        .limit(1)
    )


def _expand_hosts(tasks: Sequence[Any]) -> dict[tuple[str, str, str, int], tuple[str, int]]:
    """Expand tasks to host rows: (play, task, host, occurrence_idx) -> (status, seq).

    occurrence_idx counts duplicate (play, task, host) keys in seq order so repeated
    task names (loops/includes) align positionally instead of colliding.
    """
    counts: dict[tuple[str, str, str], int] = {}
    out: dict[tuple[str, str, str, int], tuple[str, int]] = {}
    for t in tasks:
        for host, host_status in (t.hosts or {}).items():
            base = (t.play_name, t.name, host)
            idx = counts.get(base, 0)
            counts[base] = idx + 1
            out[(t.play_name, t.name, host, idx)] = (host_status, t.seq)
    return out


def _expand_durations(tasks: Sequence[Any]) -> dict[tuple[str, str, int], tuple[float | None, int]]:
    """Task-level (NOT per-host) expansion: (play, task, occurrence_idx) -> (duration_s, seq)."""
    counts: dict[tuple[str, str], int] = {}
    out: dict[tuple[str, str, int], tuple[float | None, int]] = {}
    for t in tasks:
        base = (t.play_name, t.name)
        idx = counts.get(base, 0)
        counts[base] = idx + 1
        out[(t.play_name, t.name, idx)] = (t.duration_s, t.seq)
    return out


def diff_tasks(cur_tasks: Sequence[Any], base_tasks: Sequence[Any]) -> dict:
    """Pure classification of current-vs-baseline tasks.

    Returns {newly_failing, fixed, still_failing, added_count, removed_count,
    slowest_changes}. Entry lists are sorted by current-run seq (baseline-only
    entries last) and capped at MAX_ENTRIES.
    """
    cur = _expand_hosts(cur_tasks)
    base = _expand_hosts(base_tasks)

    # (sort_key, entry) pairs; sort_key puts current-run rows first, ordered by seq.
    newly_failing: list[tuple[tuple[int, int], DiffEntry]] = []
    still_failing: list[tuple[tuple[int, int], DiffEntry]] = []
    fixed: list[tuple[tuple[int, int], DiffEntry]] = []
    added_count = 0
    removed_count = 0

    for key in cur.keys() | base.keys():
        play_name, task_name, host, _idx = key
        after = cur.get(key)
        before = base.get(key)
        after_status = after[0] if after is not None else None
        before_status = before[0] if before is not None else None

        if after_status in FAIL:
            bucket = still_failing if before_status in FAIL else newly_failing
        elif before_status in FAIL and after_status is not None:
            bucket = fixed
        else:
            if before is None and after_status is not None:
                added_count += 1       # appeared, non-failing
            elif after is None:
                removed_count += 1     # present in baseline, absent now (any status)
            continue

        sort_key = (0, after[1]) if after is not None else (1, before[1])
        bucket.append((sort_key, DiffEntry(
            play_name=play_name, task_name=task_name, host=host,
            before=before_status, after=after_status,
            seq=after[1] if after is not None else before[1],
        )))

    def _finalize(pairs: Iterable[tuple[tuple[int, int], DiffEntry]]) -> list[DiffEntry]:
        return [e for _, e in sorted(pairs, key=lambda p: p[0])][:MAX_ENTRIES]

    # Task-level duration deltas (both sides need a real duration_s).
    base_durations = _expand_durations(base_tasks)
    deltas: list[DurationDelta] = []
    for dkey, (after_s, seq) in _expand_durations(cur_tasks).items():
        b = base_durations.get(dkey)
        if b is None or b[0] is None or after_s is None:
            continue
        delta = after_s - b[0]
        if abs(delta) >= MIN_DURATION_DELTA_S:
            deltas.append(DurationDelta(
                play_name=dkey[0], task_name=dkey[1], seq=seq,
                before_s=b[0], after_s=after_s, delta_s=delta,
            ))
    deltas.sort(key=lambda d: abs(d.delta_s), reverse=True)

    return {
        "newly_failing": _finalize(newly_failing),
        "fixed": _finalize(fixed),
        "still_failing": _finalize(still_failing),
        "added_count": added_count,
        "removed_count": removed_count,
        "slowest_changes": deltas[:TOP_SLOWEST],
    }


def recap_newly_unreachable(cur_recap: list[dict] | None, base_recap: list[dict] | None) -> list[str]:
    """Hosts with unreachable > 0 in the current recap that were absent-or-zero in baseline."""
    base_unreachable: dict[str, int] = {}
    for row in base_recap or []:
        host = row.get("host")
        if host:
            base_unreachable[host] = int(row.get("unreachable", 0) or 0)
    out: list[str] = []
    for row in cur_recap or []:
        host = row.get("host")
        if not host:
            continue
        if int(row.get("unreachable", 0) or 0) > 0 and base_unreachable.get(host, 0) == 0:
            out.append(host)
    return out
