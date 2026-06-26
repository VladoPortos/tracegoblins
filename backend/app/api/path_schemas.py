from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_serializer


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
    taken_hosts: list[str] | None = None
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
    never_run: bool = False


class PathEdgeOut(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    from_: str = Field(alias="from")
    to: str
    branch: str | None = None


class PathViewOut(BaseModel):
    type: str
    id: str | None = None

    @model_serializer
    def _ser(self) -> dict:
        return {"type": self.type} if self.id is None else {"type": self.type, "id": self.id}


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


class ResolvedValueOut(BaseModel):
    key: str
    expr: str | None = None         # source template, if known (e.g. "{{ pkg }}")
    value: Any | None = None        # rendered value; None when not recorded
    source: str                     # module_args | task_args | item | when | extra_vars
    recorded: bool = True           # False → render raw expr + "not recorded"
    host: str | None = None         # representative host when value is per-host


class NodeSourceOut(BaseModel):
    project_id: str | None = None
    path: str | None = None
    ref: str | None = None
    content: str | None = None
    focus_line: int | None = None
    executed_lines: list[int] = []
    never_run_lines: list[int] = []
    resolved: list[ResolvedValueOut] = []
    hosts: list[str] = []
    unavailable: str | None = None  # not_linked|not_cloned|revision_missing|no_path|binary|too_large
