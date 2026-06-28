from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

UNCHANGED_SECRET = "$unchanged$"  # sentinel: PUT /git leaves the stored secret intact


class ProjectListItem(BaseModel):
    id: str
    name: str
    controller_id: str
    controller_name: str | None
    scm_type: str
    scm_branch: str | None
    status: str                       # unlinked|pending|cloning|cloned|error
    linked_run_count: int


class ProjectListOut(BaseModel):
    items: list[ProjectListItem]
    total: int


class ProjectOut(BaseModel):
    id: str
    controller_id: str
    controller_name: str | None
    awx_project_id: int
    name: str
    scm_type: str
    scm_url: str | None
    scm_branch: str | None
    scm_revision: str | None
    description: str | None
    organization_id: int | None
    organization_name: str | None
    status: str
    effective_git_url: str | None     # coalesce(git_url_override, scm_url)
    git_url_override: str | None
    git_auth_type: str | None
    git_username: str | None
    has_git_secret: bool              # whether a secret is stored — NEVER the secret itself
    last_clone_at: datetime | None
    last_clone_error: str | None
    clone_size_bytes: int | None
    linked_run_count: int
    created_at: datetime
    updated_at: datetime


class ProjectGitIn(BaseModel):
    git_url_override: str | None = Field(default=None, max_length=2048)
    auth_type: Literal["none", "token", "userpass"] = "none"
    username: str | None = Field(default=None, max_length=255)
    # write-only secret. Omitted/sentinel → leave intact; "" → clear; non-empty → set.
    secret: str | None = Field(default=UNCHANGED_SECRET, max_length=4096)


class TreeEntryOut(BaseModel):
    name: str
    type: str                         # "blob" | "tree"
    size: int | None = None
    mode: str


class TreeOut(BaseModel):
    ref: str
    path: str
    entries: list[TreeEntryOut]


class BlobOut(BaseModel):
    ref: str
    path: str
    content: str | None               # None when binary or too_large
    size: int
    too_large: bool
    binary: bool
