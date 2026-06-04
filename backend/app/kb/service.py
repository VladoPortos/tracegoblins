from __future__ import annotations

import logging
import uuid

import sqlalchemy as sa
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.kb.matcher import match_error
from app.models import (
    ControllerTeam, KbOccurrence, KbSignature, Run, RunShare, Task, TeamMember, User,
)
from app.services.visibility import my_team_ids

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


async def _run_visible_cond(db: AsyncSession, user: User):
    """A SQL predicate over `Run` matching is_run_visible's five paths for viewer U.

    owner ∪ team-owned ∪ direct-share ∪ team-share ∪ AWX-via-controller_teams.
    A1: admin role grants NO path — purely relationship-based.

    NOTE — this is the THIRD hand-copy of the 5-path visibility disjunction (alongside
    `is_run_visible` in app/services/visibility.py:16 and `runs.py::_team_scope_base`). It
    mirrors `is_run_visible` in FULL — the **owner path is INCLUDED** so a viewer's OWN
    personal uploads count toward "seen in N runs". It is INTENTIONALLY NOT `_team_scope_base`,
    which deliberately EXCLUDES the owner's personal uploads (that helper scopes a team's
    shared view, not a single viewer's). Keep this aligned with `is_run_visible`, not with
    `_team_scope_base`, if any of the three ever change.
    """
    team_ids = await my_team_ids(db, user)
    owner = Run.owner_user_id == user.id        # owner path — INCLUDED (unlike _team_scope_base)
    team_owned = Run.team_id.in_(team_ids) if team_ids else sa.false()
    direct = Run.id.in_(
        select(RunShare.run_id).where(RunShare.shared_with_user_id == user.id)
    )
    team_share = (
        Run.id.in_(select(RunShare.run_id).where(RunShare.shared_with_team_id.in_(team_ids)))
        if team_ids else sa.false()
    )
    awx = (
        (Run.source == "awx")
        & Run.controller_id.in_(
            select(ControllerTeam.controller_id).where(
                ControllerTeam.team_id.in_(team_ids),
                or_(
                    ControllerTeam.awx_organization_id.is_(None),
                    ControllerTeam.awx_organization_id == Run.awx_organization_id,
                ),
            )
        )
        if team_ids else sa.false()
    )
    return owner | team_owned | direct | team_share | awx


async def visible_occurrence_count(
    db: AsyncSession, signature_id: uuid.UUID, user: User
) -> int:
    """"Also seen in N runs" — DISTINCT runs of `signature_id` that U can see.

    The API layer must already have confirmed U may see the signature; this counts
    only occurrences whose run is visible to U, so an invisible run never leaks (A1).
    """
    cond = await _run_visible_cond(db, user)
    n = await db.scalar(
        select(func.count(func.distinct(KbOccurrence.run_id)))
        .select_from(KbOccurrence)
        .join(Run, Run.id == KbOccurrence.run_id)
        .where(KbOccurrence.signature_id == signature_id, cond)
    )
    return int(n or 0)


async def recent_visible_occurrences(
    db: AsyncSession, signature_id: uuid.UUID, user: User, *, limit: int = 5
) -> list[tuple[KbOccurrence, Run]]:
    """The latest `limit` (occurrence, run) pairs for `signature_id` visible to U.

    Ordered by the run's recency (log_time, then created_at). Used by the drawer card
    "recent runs" list; visibility-scoped exactly like visible_occurrence_count.
    """
    cond = await _run_visible_cond(db, user)
    when = func.coalesce(Run.log_time, Run.created_at)
    rows = (await db.execute(
        select(KbOccurrence, Run)
        .join(Run, Run.id == KbOccurrence.run_id)
        .where(KbOccurrence.signature_id == signature_id, cond)
        .order_by(when.desc(), KbOccurrence.matched_at.desc())
        .limit(limit)
    )).all()
    return [(occ, run) for occ, run in rows]
