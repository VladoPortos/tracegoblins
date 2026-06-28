from __future__ import annotations

from collections import defaultdict
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.clock import utcnow
from app.core.statuses import FAIL_STATUSES
from app.models import Run, User
from app.services.run_time import run_when_expr
from app.services.visibility import run_visible_cond

SPARK_N = 20  # sparkline length sent to the UI


async def template_stats(db: AsyncSession, user: User, *, days: int) -> list[dict]:
    """Per-template aggregates over the viewer-visible runs in the window.

    Python-side aggregation: the window holds a few thousand slim rows at design
    scale (D8), and streak/flip/recovery logic is much clearer in Python than SQL.
    """
    cond = await run_visible_cond(db, user)
    # Effective run timestamp (prefer AWX launch, then finish/log, then import) — the one
    # ordering rule lives in app.services.run_time. created_at breaks effective-time ties so
    # the oldest→newest sequence (and thus streak/flip/recovery math) is deterministic.
    when = run_when_expr()
    rows = (await db.execute(
        select(Run.id, Run.template_name, Run.status, Run.elapsed, when.label("when"))
        .where(cond, when >= utcnow() - timedelta(days=days))
        .order_by(when.asc(), Run.created_at.asc(), Run.id.asc())
    )).all()

    # Group by the real template name; None/"" share the null bucket. A real template
    # literally named "(untitled)" stays separate (the display label is applied at output).
    groups: dict[str | None, list] = defaultdict(list)
    for r in rows:
        groups[r.template_name or None].append(r)

    out: list[dict] = []
    for name, runs in groups.items():
        fails = [r.status in FAIL_STATUSES for r in runs]
        failed = sum(fails)
        flips = sum(1 for a, b in zip(fails, fails[1:]) if a != b)
        streak = 1
        for f in reversed(fails[:-1]):
            if f != fails[-1]:
                break
            streak += 1
        durations = [r.elapsed for r in runs if r.elapsed is not None]
        recoveries: list[float] = []
        first_fail = None
        for r, f in zip(runs, fails):
            if f and first_fail is None:
                first_fail = r.when
            elif not f and first_fail is not None:
                recoveries.append((r.when - first_fail).total_seconds())
                first_fail = None
        out.append({
            "template_name": name or "(untitled)",
            "runs": len(runs), "failed": failed, "succeeded": len(runs) - failed,
            "success_rate": (len(runs) - failed) / len(runs),
            "current_streak": streak,
            "streak_kind": "fail" if fails[-1] else "pass",
            "flips": flips,
            "flaky_score": flips / (len(runs) - 1) if len(runs) > 1 else 0.0,
            "avg_duration_s": sum(durations) / len(durations) if durations else None,
            # Mean across fail→recover cycles in the window (None if never recovered).
            "time_to_recovery_s": sum(recoveries) / len(recoveries) if recoveries else None,
            "last_status": runs[-1].status, "last_when": runs[-1].when,
            "last_run_id": str(runs[-1].id),
            "recent": [r.status for r in runs[-SPARK_N:]],
            "recent_ids": [str(r.id) for r in runs[-SPARK_N:]],
        })
    # Worst first; last_run_id (unique per group) is the final tiebreaker so ordering is
    # total even when two rows share a label — e.g. null-named runs and a real template
    # literally named "(untitled)" both render as "(untitled)" but stay deterministically ordered.
    out.sort(key=lambda d: (d["success_rate"], -d["runs"], d["template_name"], d["last_run_id"]))
    return out
