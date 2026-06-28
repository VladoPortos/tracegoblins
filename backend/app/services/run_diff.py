"""Diff a run against its last green baseline (same template, older, visible).

`find_baseline` is the only DB-touching function; `diff_tasks` and
`recap_newly_unreachable` are pure so they stay unit-testable without a DB.
"""

from __future__ import annotations

from typing import Any, Iterable, Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.runs_schemas import DiffEntry, DurationDelta
from app.core.statuses import FAIL_STATUSES as FAIL
from app.models import Run, User
from app.services.run_time import run_effective_when, run_when_expr
from app.services.visibility import run_visible_cond

# NOTE: a "host actually passed" is ok/changed ONLY — a host that went failed→skipped/included did
# NOT pass, so GREEN_HOST is intentionally NARROWER than statuses.GREEN_STATUSES (which has skipped).
GREEN = ("ok", "changed")
# Host-level "actually passed": a real fix is ok/changed only. A host that goes
# failed -> skipped/included did NOT pass (it stopped running), so it must not be
# advertised as fixed. Derived from GREEN so the one ordering rule lives in one place.
GREEN_HOST = frozenset(GREEN)
MAX_ENTRIES = 200          # hard cap per entry list — never unbounded
MIN_DURATION_DELTA_S = 5.0  # ignore sub-5s task duration noise
TOP_SLOWEST = 5


async def find_baseline(db: AsyncSession, run: Run, user: User) -> Run | None:
    """The most recent VISIBLE green run of the same template strictly older than `run`.

    Effective time is coalesce(launched_at, log_time, created_at) on both sides.
    Visibility uses the canonical single-viewer predicate (A1: admin grants nothing).
    Effective-time ties break toward the more recently ingested run (created_at desc),
    with Run.id as the final deterministic fallback, so the baseline is reproducible.
    """
    if run.template_name is None:
        return None
    run_when = run_effective_when(run)
    when = run_when_expr()
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
        .order_by(when.desc(), Run.created_at.desc(), Run.id.asc())
        .limit(1)
    )


def _expand_hosts(tasks: Sequence[Any]) -> dict[tuple[str, str, str, int], tuple[str, int]]:
    """Expand tasks to host rows: (play, task, host, occurrence_idx) -> (status, seq).

    occurrence_idx counts duplicate (play, task, host) keys in seq order so repeated
    task names (loops/includes) align positionally instead of colliding.

    Heuristic limitation: there is no stable cross-run identity for a loop/include
    iteration, so alignment is purely positional. If a repeated task's occurrence
    *count* differs between baseline and current, the surplus occurrences pair with
    nothing (surfacing as spurious added/removed), and a shifted failing iteration
    can produce a paired spurious newly_failing + fixed. Acceptable for an advisory
    diff at design scale; revisit only if per-iteration identity is ever recorded.
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
    """Task-level (NOT per-host) expansion: (play, task, occurrence_idx) -> (duration_s, seq).

    Positional occurrence_idx, same heuristic limitation as _expand_hosts: a loop/include
    whose iteration count changes between runs can misalign duration deltas.
    """
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
    slowest_changes}. Entry lists are sorted by current-run seq, then host (a total
    order so multi-host rows of one task are stable), and capped at MAX_ENTRIES.
    """
    cur = _expand_hosts(cur_tasks)
    base = _expand_hosts(base_tasks)

    # (sort_key, entry) pairs; sort_key puts current-run rows first, ordered by seq.
    newly_failing: list[tuple[tuple[int, int, str], DiffEntry]] = []
    still_failing: list[tuple[tuple[int, int, str], DiffEntry]] = []
    fixed: list[tuple[tuple[int, int, str], DiffEntry]] = []
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
        elif before_status in FAIL and after_status in GREEN_HOST:
            bucket = fixed       # only a genuine pass (ok/changed) counts as a fix
        else:
            # A failed/unreachable host that is now skipped/included lands here: it did
            # not pass, so it is neither fixed nor failing. Only real add/remove is counted.
            if before is None and after_status is not None:
                added_count += 1       # appeared, non-failing
            elif after is None:
                removed_count += 1     # present in baseline, absent now (any status)
            continue

        # Every bucketed entry reaches here via after_status in FAIL or GREEN_HOST, both of
        # which require after is not None, so the current-run seq is always available. host is
        # the final sort tiebreaker so multi-host rows of one task have a deterministic order
        # (the cur.keys()|base.keys() set union above is otherwise hash-ordered).
        bucket.append(((0, after[1], host), DiffEntry(
            play_name=play_name, task_name=task_name, host=host,
            before=before_status, after=after_status, seq=after[1],
        )))

    def _finalize(pairs: Iterable[tuple[tuple[int, int, str], DiffEntry]]) -> list[DiffEntry]:
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
