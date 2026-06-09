from __future__ import annotations

from collections import defaultdict
from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.clock import utcnow
from app.models import Run, User
from app.services.visibility import run_visible_cond

FAIL_STATUSES = {"failed", "unreachable"}
SPARK_N = 20  # sparkline length sent to the UI


async def template_stats(db: AsyncSession, user: User, *, days: int) -> list[dict]:
    """Per-template aggregates over the viewer-visible runs in the window.

    Python-side aggregation: the window holds a few thousand slim rows at design
    scale (D8), and streak/flip/recovery logic is much clearer in Python than SQL.
    """
    cond = await run_visible_cond(db, user)
    # Effective run timestamp — mirrors runs.py::_when_expr() (prefer AWX launch,
    # then finish/log, then import). Kept inline so services don't import API modules.
    when = func.coalesce(Run.launched_at, Run.log_time, Run.created_at)
    rows = (await db.execute(
        select(Run.id, Run.template_name, Run.status, Run.elapsed, when.label("when"))
        .where(cond, when >= utcnow() - timedelta(days=days))
        .order_by(when.asc(), Run.id.asc())
    )).all()

    groups: dict[str, list] = defaultdict(list)
    for r in rows:
        groups[r.template_name or "(untitled)"].append(r)

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
            "template_name": name,
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
    # Worst first; template name as final tiebreaker for deterministic ordering.
    out.sort(key=lambda d: (d["success_rate"], -d["runs"], d["template_name"]))
    return out
