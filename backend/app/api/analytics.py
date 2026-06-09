from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Query
from pydantic import BaseModel

from app.api.deps import CurrentUser, DbSession
from app.services.analytics import template_stats

router = APIRouter(prefix="/api/analytics", tags=["analytics"])


class TemplateStat(BaseModel):
    template_name: str
    runs: int
    failed: int
    succeeded: int
    success_rate: float
    current_streak: int
    streak_kind: str            # 'pass' | 'fail'
    flips: int
    flaky_score: float          # flips / (runs-1); 0 when runs < 2
    avg_duration_s: float | None
    time_to_recovery_s: float | None  # mean seconds from a failure streak's first fail to the next pass
    last_status: str
    last_when: datetime | None
    last_run_id: str
    recent: list[str]           # last ≤20 statuses, oldest→newest
    recent_ids: list[str]


class TemplateStatsOut(BaseModel):
    items: list[TemplateStat]
    window_days: int


@router.get("/templates", response_model=TemplateStatsOut)
async def get_template_stats(
    db: DbSession,
    user: CurrentUser,
    days: int = Query(30, ge=1, le=365),
) -> TemplateStatsOut:
    items = await template_stats(db, user, days=days)
    return TemplateStatsOut(items=[TemplateStat(**d) for d in items], window_days=days)
