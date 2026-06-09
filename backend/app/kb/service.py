from __future__ import annotations

import logging
import uuid

from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.kb.matcher import match_error
from app.models import (
    ControllerTeam, KbOccurrence, KbSignature, Run, RunShare, Task, TeamMember, User,
)
from app.services.visibility import my_team_ids, run_visible_cond

logger = logging.getLogger(__name__)

_FAILED_STATUSES = frozenset({"failed", "unreachable"})
_BACKFILL_RUN_CAP = 500  # bounded scan (medium scale, D8)


async def run_audience_team_ids(db: AsyncSession, run: Run) -> set[uuid.UUID]:
    """The set of team ids a run "belongs to" for KB match scope (spec M5-D6).

    team-owned upload -> {run.team_id}; AWX run -> the org-aware controller_teams;
    personal upload -> the uploader's teams. Union (may be empty -> global-only).
    """
    teams: set[uuid.UUID] = set()

    if run.team_id is not None:
        teams.add(run.team_id)

    if run.source == "awx" and run.controller_id is not None:
        rows = (await db.execute(
            select(ControllerTeam.team_id).where(
                ControllerTeam.controller_id == run.controller_id,
                or_(
                    ControllerTeam.awx_organization_id.is_(None),
                    ControllerTeam.awx_organization_id == run.awx_organization_id,
                ),
            )
        )).scalars().all()
        teams.update(rows)

    if run.team_id is None and run.owner_user_id is not None:
        uploader = await db.get(User, run.owner_user_id)
        if uploader is not None:
            teams.update(await my_team_ids(db, uploader))

    return teams


def _first_failed_host(task: Task) -> str | None:
    """First host on the task whose status is failed/unreachable; else None."""
    for host, status in (task.hosts or {}).items():
        if status in _FAILED_STATUSES:
            return host
    return None


async def match_run(db: AsyncSession, run: Run, *, commit: bool = True) -> int:
    """Match every failed task of `run` and upsert a deduped kb_occurrence per hit.

    Best-effort, post-commit: called AFTER the run is persisted/committed (by the M2
    ingestion route and the M4 sync loop). Computes the run's audience teams once, then
    matches each failed task. The unique constraint uq_kb_occurrences_sig_run_seq dedupes
    re-matches; a conflicting insert is undone via a per-occurrence SAVEPOINT and skipped.

    `commit` (default True): when True, commits its own occurrence writes at the end
    (the post-commit ingest/sync callers want this — the route has already committed the
    run). When False, only flushes — the CALLER owns the final commit, so the occurrences
    join the caller's transaction (the KB mutation routes pass commit=False so the
    signature insert + occurrences + audit row all commit together; see D4/D5/D8/D9).
    Returns the number of occurrences newly upserted.
    """
    team_ids = await run_audience_team_ids(db, run)

    tasks = (await db.execute(
        select(Task).where(
            Task.run_id == run.id,
            Task.status.in_(_FAILED_STATUSES),
            Task.error.isnot(None),
        ).order_by(Task.seq)
    )).scalars().all()

    upserted = 0
    for t in tasks:
        res = await match_error(db, t.error, team_ids=team_ids)
        if res is None:
            continue
        # SAVEPOINT per insert (controllers.py:99 pattern): a bare `await db.rollback()`
        # tears down the WHOLE async session transaction (controllers.py:84) — which would
        # silently discard the OTHER new occurrences in this same run on a new+dup mix.
        # begin_nested() scopes the undo to just this conflicting row.
        try:
            async with db.begin_nested():
                db.add(KbOccurrence(
                    signature_id=res.signature.id,
                    run_id=run.id,
                    task_seq=t.seq,
                    host=_first_failed_host(t),
                ))
                await db.flush()
            upserted += 1
        except IntegrityError:
            # Already recorded (re-match): the unique constraint fired. The SAVEPOINT
            # rolled back just this one insert — re-matching a run is idempotent.
            continue

    if commit:
        await db.commit()
    return upserted


async def backfill_signature(db: AsyncSession, sig: KbSignature, *, commit: bool = True) -> int:
    """Re-scan recent in-scope failed runs and record occurrences for `sig`.

    Called on KB create/edit/promote-global. Bounded by _BACKFILL_RUN_CAP most-recent
    runs (medium scale, D8 — no unbounded scan, security §11). Reuses match_run per
    candidate run, so the run-audience scope + dedupe-upsert are identical to ingest/sync.

    `commit` (default True): threaded straight through to every per-run match_run call.
    The KB mutation routes (D4 create / D5 edit / D8 promote / D9 promote-global) pass
    commit=False so the new signature's occurrences join the route's single final
    db.commit() ALONGSIDE the audit row — backfill committing mid-route would persist the
    signature + its occurrences BEFORE the audit row, breaking audit atomicity (a forced
    failure after backfill must leave NEITHER the signature NOR an audit row).
    Returns the total occurrences upserted across the candidate runs.
    """
    if sig.team_id is None:
        # Global: every run is a candidate.
        run_cond = None
    else:
        team_id = sig.team_id
        # Members of the signature's team (their personal uploads scope to this team too).
        member_ids = (await db.execute(
            select(TeamMember.user_id).where(TeamMember.team_id == team_id)
        )).scalars().all()

        team_owned = Run.team_id == team_id
        team_shared = Run.id.in_(
            select(RunShare.run_id).where(RunShare.shared_with_team_id == team_id)
        )
        awx_visible = (Run.source == "awx") & Run.controller_id.in_(
            select(ControllerTeam.controller_id).where(
                ControllerTeam.team_id == team_id,
                or_(
                    ControllerTeam.awx_organization_id.is_(None),
                    ControllerTeam.awx_organization_id == Run.awx_organization_id,
                ),
            )
        )
        member_personal = (
            (Run.source != "awx") & Run.team_id.is_(None)
            & Run.owner_user_id.in_(member_ids)
        ) if member_ids else None

        conds = [team_owned, team_shared, awx_visible]
        if member_personal is not None:
            conds.append(member_personal)
        run_cond = or_(*conds)

    stmt = select(Run)
    if run_cond is not None:
        stmt = stmt.where(run_cond)
    stmt = stmt.order_by(Run.created_at.desc()).limit(_BACKFILL_RUN_CAP)
    candidate_runs = (await db.execute(stmt)).scalars().all()

    total = 0
    for run in candidate_runs:
        total += await match_run(db, run, commit=commit)
    return total


async def visible_occurrence_count(
    db: AsyncSession, signature_id: uuid.UUID, user: User
) -> int:
    """"Also seen in N runs" — DISTINCT runs of `signature_id` that U can see.

    The API layer must already have confirmed U may see the signature; this counts
    only occurrences whose run is visible to U, so an invisible run never leaks (A1).
    """
    cond = await run_visible_cond(db, user)
    n = await db.scalar(
        select(func.count(func.distinct(KbOccurrence.run_id)))
        .select_from(KbOccurrence)
        .join(Run, Run.id == KbOccurrence.run_id)
        .where(KbOccurrence.signature_id == signature_id, cond)
    )
    return int(n or 0)


async def visible_occurrence_counts(
    db: AsyncSession, signature_ids: list[uuid.UUID], user: User
) -> dict[uuid.UUID, int]:
    """Batched visibility-scoped DISTINCT-run occurrence counts for many signatures (ONE query).

    Same semantics as visible_occurrence_count() but for a set of signatures at once, so the
    KB list view doesn't fire one COUNT per signature (N+1). Signatures with zero visible
    occurrences are simply absent from the result — callers default to 0.
    """
    if not signature_ids:
        return {}
    cond = await run_visible_cond(db, user)
    rows = (await db.execute(
        select(
            KbOccurrence.signature_id,
            func.count(func.distinct(KbOccurrence.run_id)),
        )
        .select_from(KbOccurrence)
        .join(Run, Run.id == KbOccurrence.run_id)
        .where(KbOccurrence.signature_id.in_(signature_ids), cond)
        .group_by(KbOccurrence.signature_id)
    )).all()
    return {sig_id: int(n or 0) for sig_id, n in rows}
