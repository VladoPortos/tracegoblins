from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class EnterToOut(BaseModel):
    type: Literal["container", "loop"]
    id: str


class PathNodeOut(BaseModel):
    id: str
    type: str
    label: str
    sub: str | None = None
    status: str
    action: str | None = None
    host_count: int | None = None
    item_count: int | None = None
    ok_count: int | None = None
    fail_count: int | None = None
    has_failures: bool = False
    is_conditional: bool = False
    condition: str | None = None
    branch: str | None = None
    enter_to: EnterToOut | None = None
    child_count: int | None = None
    duration_s: float | None = None
    task_path: str | None = None


class PathEdgeOut(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    from_: str = Field(alias="from")
    to: str
    branch: str | None = None


class PathViewOut(BaseModel):
    type: str
    id: str | None = None


class PathTreeOut(BaseModel):
    run_id: str
    view: PathViewOut
    nodes: list[PathNodeOut]
    edges: list[PathEdgeOut]


class NodeResultOut(BaseModel):
    host: str
    item_index: int | None = None
    item_value: Any | None = None
    status: str
    changed: bool = False
    output: str | None = None
    skip_reason: str | None = None
    duration_s: float | None = None


class NodeResultsPageOut(BaseModel):
    results: list[NodeResultOut]
    total: int


class RunInputsOut(BaseModel):
    extra_vars: dict[str, Any]
    survey: dict[str, Any] | None = None
    limit: str | None = None
    scm_revision: str | None = None
    project_id: int | None = None
    project_name: str | None = None
