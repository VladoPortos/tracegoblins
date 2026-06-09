from __future__ import annotations

import json
from datetime import datetime

from pydantic import BaseModel, Field, field_validator

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
# match_patterns is reserved/free-form JSONB. Cap its serialized size so it can't be used to
# stuff unbounded JSON into the column (storage abuse) — the other KB fields are all capped.
_MATCH_PATTERNS_MAX_CHARS = 10_000


def _validate_match_patterns(cls, v):
    if v is None:
        return v
    try:
        size = len(json.dumps(v))
    except (TypeError, ValueError):
        raise ValueError("match_patterns must be JSON-serializable")
    if size > _MATCH_PATTERNS_MAX_CHARS:
        raise ValueError(f"match_patterns too large (max {_MATCH_PATTERNS_MAX_CHARS} serialized chars)")
    return v


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

    _cap_match_patterns = field_validator("match_patterns")(classmethod(_validate_match_patterns))


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

    _cap_match_patterns = field_validator("match_patterns")(classmethod(_validate_match_patterns))


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


class KbSuggestionOut(BaseModel):        # GET /api/runs/{id}/tasks/{seq}/kb — the drawer card
    signature: SignatureOut              # includes occurrence_count
    exact: bool
    score: float
