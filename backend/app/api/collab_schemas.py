from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

TAG_VALUES = frozenset({"needs-fix", "known-issue", "resolved", "note"})
ALLOWED_URL_SCHEMES = frozenset({"http", "https", "mailto"})

# Shared input caps: keep the API from accepting absurd payloads (DoS / storage abuse) and
# from overflowing bounded DB columns. Generous on purpose — real content fits comfortably.
_NOTE_MAX = 20_000
_BODY_MAX = 20_000
_LABEL_MAX = 300
_URL_MAX = 2_048
_ID_MAX = 64          # a UUID string is 36 chars
_TAGS_MAX = 20
_LINKS_MAX = 50
_MENTIONS_MAX = 200


class ShareTargetUser(BaseModel):
    id: str
    display_name: str
    email: str


class ShareTargetTeam(BaseModel):
    id: str
    name: str
    slug: str


class ShareOut(BaseModel):
    id: str
    run_id: str
    permission: str
    shared_by_user_id: str
    user: ShareTargetUser | None
    team: ShareTargetTeam | None
    created_at: datetime


class ShareCreate(BaseModel):
    user_id: str | None = Field(default=None, max_length=_ID_MAX)
    team_id: str | None = Field(default=None, max_length=_ID_MAX)  # exactly one -> else 422


# --- annotations ---

class AnnotationLink(BaseModel):
    label: str = Field(max_length=_LABEL_MAX)
    url: str = Field(max_length=_URL_MAX)  # http/https/mailto only — server-validated on write


class AnnotationOut(BaseModel):
    id: str
    run_id: str
    task_seq: int
    author_user_id: str
    author_name: str
    note: str
    tags: list[str]
    links: list[AnnotationLink]
    resolved: bool
    created_at: datetime
    updated_at: datetime


class AnnotationCreate(BaseModel):
    note: str = Field(default="", max_length=_NOTE_MAX)
    tags: list[str] = Field(default=[], max_length=_TAGS_MAX)
    links: list[AnnotationLink] = Field(default=[], max_length=_LINKS_MAX)


class AnnotationUpdate(BaseModel):
    note: str | None = Field(default=None, max_length=_NOTE_MAX)
    tags: list[str] | None = Field(default=None, max_length=_TAGS_MAX)
    links: list[AnnotationLink] | None = Field(default=None, max_length=_LINKS_MAX)
    resolved: bool | None = None


# --- comments ---

class CommentOut(BaseModel):
    id: str
    run_id: str
    task_seq: int | None
    annotation_id: str | None
    parent_id: str | None
    author_user_id: str          # author FK is ondelete=CASCADE -> never null
    author_name: str
    body: str | None  # null when soft-deleted (tombstone)
    mentions: list[str]
    mention_names: list[str]
    created_at: datetime
    edited_at: datetime | None
    deleted_at: datetime | None


class CommentCreate(BaseModel):
    body: str = Field(max_length=_BODY_MAX)
    mentions: list[str] = Field(default=[], max_length=_MENTIONS_MAX)  # validated run-visible; rest dropped
    parent_id: str | None = Field(default=None, max_length=_ID_MAX)
    annotation_id: str | None = Field(default=None, max_length=_ID_MAX)


class CommentUpdate(BaseModel):
    body: str = Field(max_length=_BODY_MAX)
    mentions: list[str] = Field(default=[], max_length=_MENTIONS_MAX)  # re-validated run-visible (C5)


# --- mention autocomplete ---

class MentionableUser(BaseModel):
    id: str
    display_name: str
    email: str
    initials: str | None = None
    avatar_color: str | None = None


# --- notifications (defined here in Phase B so Phase C imports cleanly without circular deps) ---

class NotificationOut(BaseModel):
    id: str
    type: str                             # "mention" | "share"
    run_id: str | None                    # null if run deleted (SET NULL)
    run_template: str | None              # denormalized: runs.template_name
    comment_id: str | None
    task_seq: int | None                  # for deep-link to the task drawer
    task_name: str | None                 # denormalized task display
    actor_user_id: str | None
    actor_name: str | None                # denormalized; null if actor deleted
    read_at: datetime | None
    created_at: datetime


class NotificationListOut(BaseModel):
    items: list[NotificationOut]
    total: int
    unread: int


class UnreadCountOut(BaseModel):
    count: int


class MarkReadIn(BaseModel):
    ids: list[str] | None = None
    all: bool = False
