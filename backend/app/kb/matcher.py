from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.kb.signature import Signature, extract_signature
from app.models import KbSignature


@dataclass
class MatchResult:
    signature: KbSignature   # the matched ORM row
    exact: bool              # True = exact signature_key hit; False = fuzzy
    score: float             # 1.0 for exact; the pg_trgm similarity for fuzzy
    extracted: Signature     # the Signature extract_signature() produced for this error


async def match_error(
    db: AsyncSession, error_text: str | None, *, team_ids: set[uuid.UUID]
) -> MatchResult | None:
    """Match a task error to the best visible KB signature.

    Exact `signature_key` first (a team entry beats global on a tie); else `pg_trgm`
    fuzzy on `representative_text` above `settings.kb_match_threshold`. Scope is
    `team_id IS NULL` (global) ∪ `team_id ∈ team_ids`; an empty `team_ids` degrades to
    global-only, which is correct. Returns None when nothing extracts or nothing matches.
    """
    sig = extract_signature(error_text)
    if sig is None:
        return None

    # Scope predicate reused by both lookups: global ∪ the run's audience teams.
    scope = (KbSignature.team_id.is_(None)) | (KbSignature.team_id.in_(team_ids))

    # Exact: team_id IS NOT NULL sorts first so a team entry beats global on a tie. When the
    # caller spans multiple teams that each defined the same signature_key, add a DETERMINISTIC
    # tiebreaker (most-recently-updated, then id) so the chosen match is stable across requests
    # rather than whatever order the DB happens to return.
    exact_row = await db.scalar(
        select(KbSignature)
        .where(scope, KbSignature.signature_key == sig.signature_key)
        .order_by(
            KbSignature.team_id.isnot(None).desc(),
            KbSignature.updated_at.desc(),
            KbSignature.id,
        )
        .limit(1)
    )
    if exact_row is not None:
        return MatchResult(signature=exact_row, exact=True, score=1.0, extracted=sig)

    # Fuzzy: the % operator lets the GIN trgm index prefilter, and the explicit >= check
    # below is authoritative. CRITICAL: the % operator's cutoff is the session GUC
    # pg_trgm.similarity_threshold (Postgres default 0.3). If KB_MATCH_THRESHOLD is set
    # BELOW 0.3, the % prefilter would silently drop a row whose similarity is in
    # [threshold, 0.3) BEFORE the >= check ever sees it. Pin the GUC to our threshold (per
    # transaction) so the % prefilter and the >= check agree at any configured threshold.
    # NOTE: `SET LOCAL <guc> = $1` is a Postgres SYNTAX ERROR — SET does not accept bind
    # parameters. set_config(name, value, is_local=true) is the parameterizable, transaction
    # -local equivalent; its value arg is text, so pass the float coerced to str.
    await db.execute(
        text("SELECT set_config('pg_trgm.similarity_threshold', :t, true)"),
        {"t": str(float(settings.kb_match_threshold))},
    )
    similarity = func.similarity(KbSignature.representative_text, sig.representative_text)
    row = (await db.execute(
        select(KbSignature, similarity.label("score"))
        .where(scope, KbSignature.representative_text.op("%")(sig.representative_text))
        # Deterministic tiebreaker (updated_at, id) so equal-similarity matches are stable.
        .order_by(similarity.desc(), KbSignature.updated_at.desc(), KbSignature.id)
        .limit(1)
    )).first()
    if row is None:
        return None
    matched, score = row
    if float(score) < settings.kb_match_threshold:
        return None
    return MatchResult(signature=matched, exact=False, score=float(score), extracted=sig)
