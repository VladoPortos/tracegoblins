from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator


def _require_nonblank(cls, v: str | None) -> str | None:
    if v is None:
        return v
    v = v.strip()
    if not v:
        raise ValueError("must not be blank")
    return v


class TeamAssignment(BaseModel):
    team_id: str = Field(max_length=64)
    awx_organization_id: int | None = Field(default=None, gt=0)  # None = all orgs; AWX org ids are 1-based


class ControllerTeamOut(BaseModel):
    team_id: str
    team_name: str | None
    awx_organization_id: int | None


class ControllerCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    base_url: str = Field(min_length=1, max_length=2048)
    token: str = Field(min_length=1, max_length=4096)  # plaintext IN only; never echoed
    verify_ssl: bool = True
    sync_mode: Literal["manual", "auto"] = "manual"
    sync_interval_minutes: int | None = None       # required when sync_mode='auto'
    team_assignments: list[TeamAssignment] = Field(default=[], max_length=200)

    _name_nonblank = field_validator("name")(classmethod(_require_nonblank))


class ControllerUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=200)
    base_url: str | None = Field(default=None, max_length=2048)
    token: str | None = Field(default=None, max_length=4096)  # omitted/None = unchanged; set = rotate
    verify_ssl: bool | None = None
    sync_mode: Literal["manual", "auto"] | None = None
    sync_interval_minutes: int | None = None
    team_assignments: list[TeamAssignment] | None = Field(default=None, max_length=200)  # None=leave; []=clear

    _name_nonblank = field_validator("name")(classmethod(_require_nonblank))


class ControllerOut(BaseModel):
    id: str
    name: str
    base_url: str
    verify_ssl: bool
    sync_mode: str
    sync_interval_minutes: int | None
    status: str                                    # unconfigured|connected|error
    last_sync_status: str                          # never|running|ok|error
    last_sync_at: datetime | None
    last_sync_error: str | None
    sync_total: int | None = None
    sync_done: int | None = None
    sync_current_job: str | None = None
    token_masked: str                              # mask_token(decrypt_token(...)) — NEVER the token
    team_assignments: list[ControllerTeamOut]
    created_at: datetime


class TestConnectionIn(BaseModel):
    base_url: str | None = None                    # ad-hoc test before save (optional)
    token: str | None = None
    verify_ssl: bool | None = None


class TestConnectionOut(BaseModel):
    ok: bool
    version: str | None = None
    identity: str | None = None
    error: str | None = None


class SyncStartedOut(BaseModel):
    status: str                                    # "started"
