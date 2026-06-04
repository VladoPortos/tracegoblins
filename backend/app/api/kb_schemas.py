from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from app.api.collab_schemas import AnnotationLink

# The four KB lifecycle states (mirror collab_schemas.TAG_VALUES; reused for 422 validation).
KB_STATUS_VALUES = frozenset({"needs-fix", "known-issue", "resolved", "note"})

# Input caps for KB free-text (TEXT columns; bound the API surface against storage abuse).
_KEY_MAX = 1_000
_TITLE_MAX = 300
_CAT_MAX = 120
_REP_MAX = 8_000
_PROSE_MAX = 20_000
_ID_MAX = 64
_LINKS_MAX = 50


class SignatureCreate(BaseModel):
    signature_key: str = Field(max_length=_KEY_MAX)
    representative_text: str = Field(max_length=_REP_MAX)
    title: str = Field(max_length=_TITLE_MAX)
    status: str = "needs-fix"            # validated in KB_STATUS_VALUES at the route
    team_id: str | None = Field(default=None, max_length=_ID_MAX)  # None = global (admin); else U's team
    category: str | None = Field(default=None, max_length=_CAT_MAX)
    description: str | None = Field(default=None, max_length=_PROSE_MAX)
    is_problem: str | None = Field(default=None, max_length=_PROSE_MAX)
    where_it_lives: str | None = Field(default=None, max_length=_PROSE_MAX)
    match_patterns: dict | None = None
    links: list[AnnotationLink] = Field(default=[], max_length=_LINKS_MAX)


class SignatureUpdate(BaseModel):        # all optional (PATCH semantics)
    title: str | None = Field(default=None, max_length=_TITLE_MAX)
    status: str | None = None
    representative_text: str | None = Field(default=None, max_length=_REP_MAX)
    category: str | None = Field(default=None, max_length=_CAT_MAX)
    description: str | None = Field(default=None, max_length=_PROSE_MAX)
    is_problem: str | None = Field(default=None, max_length=_PROSE_MAX)
    where_it_lives: str | None = Field(default=None, max_length=_PROSE_MAX)
    match_patterns: dict | None = None
    links: list[AnnotationLink] | None = Field(default=None, max_length=_LINKS_MAX)


class SignatureOut(BaseModel):
    id: str
    team_id: str | None
    signature_key: str
    title: str
    status: str
    category: str | None
    description: str | None
    is_problem: str | None
    where_it_lives: str | None
    representative_text: str
    links: list[AnnotationLink]
    created_by_user_id: str | None
    occurrence_count: int                # visibility-scoped (§4 helper) for the requesting U
    created_at: datetime
    updated_at: datetime


class PromoteIn(BaseModel):
    run_id: str = Field(max_length=_ID_MAX)
    task_seq: int
    team_id: str | None = Field(default=None, max_length=_ID_MAX)  # None = global (admin only)
    title: str = Field(max_length=_TITLE_MAX)
    status: str = "needs-fix"
    description: str | None = Field(default=None, max_length=_PROSE_MAX)
    is_problem: str | None = Field(default=None, max_length=_PROSE_MAX)
    where_it_lives: str | None = Field(default=None, max_length=_PROSE_MAX)
    links: list[AnnotationLink] = Field(default=[], max_length=_LINKS_MAX)


class SuggestOut(BaseModel):             # GET /api/kb/suggest — auto-extracted, no write
    signature_key: str
    representative_text: str
    category: str | None


class OccurrenceRunBrief(BaseModel):
    run_id: str
    template_name: str | None
    status: str
    log_time: datetime | None
    task_seq: int
    host: str | None


class KbSuggestionOut(BaseModel):        # GET /api/runs/{id}/tasks/{seq}/kb — the drawer card
    signature: SignatureOut              # includes occurrence_count
    exact: bool
    score: float
    recent_runs: list[OccurrenceRunBrief]   # visibility-scoped recent occurrences (cap 5)
